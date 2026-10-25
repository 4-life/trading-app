import shutil
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select, text

from app.config import settings
from app.db import async_session
from app.exchange.base import MarketAdapter
from app.execution_engine.live import live_client
from app.execution_engine.models import Position, TradingDecision
from app.market_data.assets import configured_assets, probe_asset
from app.market_data.models import OrderBookSnapshot, Trade
from app.notifications.error_reporting import describe
from app.papers.models import Paper
from app.watchdog.redis_client import get_redis, heartbeat_age_seconds
from app.watchdog.results import CheckResult


async def check_database() -> CheckResult:
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return CheckResult("database", True, "reachable")
    except Exception as e:
        return CheckResult("database", False, f"unreachable: {describe(e)}")


async def check_redis() -> CheckResult:
    try:
        await get_redis().ping()
        return CheckResult("redis", True, "reachable")
    except Exception as e:
        return CheckResult("redis", False, f"unreachable: {describe(e)}")


async def check_exchange_connectivity(adapter: MarketAdapter) -> CheckResult:
    try:
        await adapter.get_market_data(await probe_asset())
        return CheckResult("exchange_connectivity", True, "reachable")
    except Exception as e:
        return CheckResult("exchange_connectivity", False, f"unreachable: {describe(e)}")


async def check_clock_drift(adapter: MarketAdapter) -> CheckResult:
    try:
        md = await adapter.get_market_data(await probe_asset())
        drift = abs((datetime.now(UTC) - md.timestamp).total_seconds())
        ok = drift <= settings.clock_drift_max_seconds
        return CheckResult("clock_drift", ok, f"{drift:.2f}s drift vs exchange time")
    except Exception as e:
        return CheckResult("clock_drift", False, f"could not check: {describe(e)}")


async def check_market_data_freshness(adapter: MarketAdapter) -> list[CheckResult]:
    """Per collected asset (the ones the provider lists): is data still
    arriving - the newer of its last trade and its last order-book snapshot.
    A market with no trades for a while (closed index / stock perps, a quiet
    coin) still gets book snapshots, so only stopped collection fails."""
    results = []
    threshold = settings.candle_poll_seconds * settings.market_data_staleness_multiplier
    async with async_session() as session:
        for asset in (a for a in await configured_assets() if adapter.is_listed(a)):
            trade = await session.scalar(
                select(func.max(Trade.exchange_timestamp)).where(Trade.asset == asset)
            )
            book = await session.scalar(
                select(func.max(OrderBookSnapshot.collected_at)).where(
                    OrderBookSnapshot.asset == asset
                )
            )
            name = f"market_data_freshness[{asset}]"
            latest = max((t for t in (trade, book) if t is not None), default=None)
            if latest is None:
                results.append(CheckResult(name, False, "no market data collected yet"))
                continue
            age = (datetime.now(UTC) - latest).total_seconds()
            trade_age = f"{(datetime.now(UTC) - trade).total_seconds():.0f}s" if trade else "never"
            detail = (
                f"last data {age:.0f}s ago, last trade {trade_age} (threshold {threshold:.0f}s)"
            )
            results.append(CheckResult(name, age <= threshold, detail))
    return results


def check_disk() -> CheckResult:
    usage = shutil.disk_usage("/")
    pct = usage.used / usage.total * 100
    ok = pct <= settings.disk_usage_max_pct
    return CheckResult("disk", ok, f"{pct:.1f}% used")


def check_memory() -> CheckResult:
    try:
        with open("/proc/meminfo") as f:
            info = {
                line.split(":")[0].strip(): int(line.split(":")[1].strip().split()[0]) for line in f
            }
        total, available = info["MemTotal"], info["MemAvailable"]
        pct = (total - available) / total * 100
        ok = pct <= settings.memory_usage_max_pct
        return CheckResult("memory", ok, f"{pct:.1f}% used")
    except OSError as e:
        return CheckResult("memory", False, f"could not check: {describe(e)}")


async def check_api() -> CheckResult:
    """The app's own API (what the dashboard talks to)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.api_url}/health")
        ok = response.status_code == 200
        return CheckResult("api", ok, f"HTTP {response.status_code}")
    except Exception as e:
        return CheckResult("api", False, f"unreachable: {describe(e)}")


async def check_order_rate() -> CheckResult:
    """Orders queued in the last minute - a runaway executor shows up here."""
    since = datetime.now(UTC) - timedelta(minutes=1)
    async with async_session() as session:
        count = await session.scalar(
            select(func.count(TradingDecision.id)).where(TradingDecision.decided_at >= since)
        )
    count = count or 0
    ok = count <= settings.max_orders_per_minute
    return CheckResult(
        "order_rate",
        ok,
        f"{count} orders in the last minute (max {settings.max_orders_per_minute})",
    )


async def check_position_protection() -> CheckResult:
    """Every open position must be managed: its paper enabled and its
    executor running (it evaluates the SL/TP every pass)."""
    async with async_session() as session:
        rows = (
            await session.execute(
                select(Position.id, Paper.id, Paper.enabled, Paper.executor)
                .join(Paper, Paper.id == Position.paper_id)
                .where(Position.closed_at.is_(None))
            )
        ).all()
    problems: list[str] = []
    ages: dict[str, float | None] = {}
    for position_id, paper_id, enabled, executor in rows:
        if not enabled:
            problems.append(f"position {position_id}: paper {paper_id} is disabled")
            continue
        if executor not in ages:
            ages[executor] = await heartbeat_age_seconds(executor)
        age = ages[executor]
        if age is None or age > settings.executor_heartbeat_stale_seconds:
            last = "never" if age is None else f"{age:.0f}s ago"
            problems.append(f"position {position_id}: executor {executor} last ran {last}")
    if problems:
        return CheckResult("position_protection", False, "; ".join(problems))
    return CheckResult("position_protection", True, f"{len(rows)} open position(s) managed")


async def check_live_reconciliation() -> CheckResult:
    """Open live positions in the database match the Hyperliquid account
    (asset, direction, size). Skipped (ok) when the live keys aren't set."""
    client = await live_client()
    if client is None:
        return CheckResult("live_reconciliation", True, "live keys not set - nothing to compare")
    try:
        exchange = {p.asset: p.size for p in await client.positions()}
    except Exception as e:
        return CheckResult("live_reconciliation", False, f"could not read positions: {describe(e)}")
    async with async_session() as session:
        rows = (
            await session.execute(
                select(Position.asset, Position.direction, Position.size).where(
                    Position.mode == "live", Position.closed_at.is_(None)
                )
            )
        ).all()
    local = {asset: size if direction == "long" else -size for asset, direction, size in rows}
    mismatches = [
        f"{asset}: app {local.get(asset, 0)} vs exchange {exchange.get(asset, 0)}"
        for asset in sorted(set(local) | set(exchange))
        if local.get(asset, 0) != exchange.get(asset, 0)
    ]
    if mismatches:
        return CheckResult("live_reconciliation", False, "; ".join(mismatches))
    return CheckResult("live_reconciliation", True, f"{len(local)} live position(s) match")
