import asyncio
import logging
from collections.abc import Awaitable
from datetime import UTC, datetime

from app.exchange.base import MarketAdapter
from app.notifications.alerts import Level, alert
from app.system import deploy
from app.watchdog.checks import (
    check_api,
    check_clock_drift,
    check_database,
    check_disk,
    check_exchange_connectivity,
    check_live_reconciliation,
    check_market_data_freshness,
    check_memory,
    check_order_rate,
    check_position_protection,
    check_redis,
)
from app.watchdog.redis_client import is_kill_switch_active, set_kill_switch, set_last_check_results
from app.watchdog.results import CheckResult

logger = logging.getLogger(__name__)

# Failures here mean the system's own view of the world can't be trusted -
# see docs/watchdog.md#on-a-critical-violation. Resource checks (disk/ram)
# and freshness are warnings, not critical, on their own.
CRITICAL_CHECKS = {
    "database",
    "exchange_connectivity",
    "clock_drift",
    "order_rate",
    "position_protection",
    "live_reconciliation",
}


# A check that doesn't answer in time fails instead of stalling the whole
# pass - a hung network call would otherwise stop the watchdog for good.
CHECK_TIMEOUT_SECONDS = 30


async def _timed(name: str, check: Awaitable[CheckResult]) -> CheckResult:
    try:
        return await asyncio.wait_for(check, CHECK_TIMEOUT_SECONDS)
    except TimeoutError:
        return CheckResult(name, False, f"no answer within {CHECK_TIMEOUT_SECONDS}s")


async def run_checks(adapter: MarketAdapter) -> list[CheckResult]:
    results = [
        await _timed("database", check_database()),
        await _timed("redis", check_redis()),
        await _timed("exchange_connectivity", check_exchange_connectivity(adapter)),
        await _timed("clock_drift", check_clock_drift(adapter)),
        await _timed("api", check_api()),
        await _timed("order_rate", check_order_rate()),
        await _timed("position_protection", check_position_protection()),
        await _timed("live_reconciliation", check_live_reconciliation()),
        check_disk(),
        check_memory(),
    ]
    try:
        freshness = await asyncio.wait_for(
            check_market_data_freshness(adapter), CHECK_TIMEOUT_SECONDS
        )
    except TimeoutError:
        no_answer = f"no answer within {CHECK_TIMEOUT_SECONDS}s"
        freshness = [CheckResult("market_data_freshness", False, no_answer)]
    results.extend(freshness)
    return results


async def report_deploy(results: list[CheckResult]) -> None:
    """After a deploy has settled (or got stuck): one summary, then the
    marker is cleared (docs/watchdog.md#deploys)."""
    current = await deploy.current()
    if current is None or not current.due(datetime.now(UTC)):
        return
    failed = [r for r in results if not r.ok]
    critical = [r for r in failed if r.name in CRITICAL_CHECKS]
    warnings = [r for r in failed if r.name not in CRITICAL_CHECKS]

    def listed(checks: list[CheckResult]) -> str:
        return "; ".join(f"{r.name}: {r.detail}" for r in checks)

    level: Level
    if current.finished_at is None:
        message = f"deploy didn't finish within {deploy.MAX_SECONDS // 60} min - alerts resumed"
        level = "critical"
    elif critical:
        message, level = f"deployed - something is broken: {listed(critical)}", "critical"
        if warnings:
            message += f" | warnings: {listed(warnings)}"
    elif warnings:
        message, level = (
            f"deployed - all critical checks passing; warnings: {listed(warnings)}",
            "warning",
        )
    else:
        message, level = "deployed - all services up, all checks passing", "info"
    await alert(deploy.SOURCE, level, message)
    await deploy.clear()


async def run_once(adapter: MarketAdapter) -> None:
    results = await run_checks(adapter)
    for r in results:
        (logger.info if r.ok else logger.warning)("%s: %s", r.name, r.detail)
    await set_last_check_results(results)
    await report_deploy(results)

    failed = [r for r in results if not r.ok]
    critical = [r for r in failed if r.name in CRITICAL_CHECKS]

    if critical:
        reasons = "; ".join(f"{r.name}: {r.detail}" for r in critical)
        await set_kill_switch(True, reason=reasons)
        await alert("watchdog", "critical", f"new positions disabled - {reasons}")
    elif await is_kill_switch_active():
        await set_kill_switch(False)
        await alert(
            "watchdog", "info", "recovered: critical checks passing again, new positions re-enabled"
        )
    elif failed:
        reasons = "; ".join(f"{r.name}: {r.detail}" for r in failed)
        await alert("watchdog", "warning", reasons)
