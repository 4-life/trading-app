import asyncio
import logging

from app.config import settings
from app.exchange.base import MarketAdapter
from app.exchange.source import connected_adapter, exit_on_source_change
from app.notifications.error_reporting import run_service
from app.watchdog.engine import run_once
from app.watchdog.redis_client import set_kill_switch

logger = logging.getLogger(__name__)


async def _check(adapter: MarketAdapter) -> None:
    while True:
        try:
            await run_once(adapter)
        except Exception:
            logger.exception("watchdog check pass failed")
        await asyncio.sleep(settings.watchdog_poll_seconds)


async def main() -> None:
    # Watchdog's checks are all REST (exchange connectivity, clock drift via
    # a REST timestamp) - it never subscribes to anything.
    source, adapter = await connected_adapter()

    # Startup gate (docs/watchdog.md#vps-failure-handling): no new positions
    # until the first check pass succeeds - run_once clears the kill switch
    # once every critical check passes.
    await set_kill_switch(True, reason="startup: checks not run yet")
    await asyncio.gather(_check(adapter), exit_on_source_change(source))


if __name__ == "__main__":
    run_service("watchdog", main)
