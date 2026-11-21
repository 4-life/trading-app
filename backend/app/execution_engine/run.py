import asyncio
import logging
import time

from app.config import settings
from app.exchange.base import MarketAdapter
from app.exchange.source import connected_adapter, exit_on_source_change
from app.execution_engine.engine import run_once
from app.execution_engine.manual_close import record_vanished
from app.notifications.error_reporting import run_service

logger = logging.getLogger(__name__)

# Live positions checked against the exchange this often (its REST is scarce).
VANISHED_CHECK_SECONDS = 60


async def _execute(adapter: MarketAdapter) -> None:
    last_vanished_check = 0.0
    while True:
        await run_once(adapter)
        if time.monotonic() - last_vanished_check >= VANISHED_CHECK_SECONDS:
            last_vanished_check = time.monotonic()
            try:
                await record_vanished()
            except Exception:
                logger.exception("checking live positions against the exchange failed")
        await asyncio.sleep(settings.execution_poll_seconds)


async def main() -> None:
    # Market prices only (REST) - no WebSocket needed.
    source, adapter = await connected_adapter()
    await asyncio.gather(_execute(adapter), exit_on_source_change(source))


if __name__ == "__main__":
    run_service("execution-engine", main)
