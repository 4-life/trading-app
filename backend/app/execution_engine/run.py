import asyncio

from app.config import settings
from app.exchange.base import MarketAdapter
from app.exchange.source import connected_adapter, exit_on_source_change
from app.execution_engine.engine import run_once
from app.notifications.error_reporting import run_service


async def _execute(adapter: MarketAdapter) -> None:
    while True:
        await run_once(adapter)
        await asyncio.sleep(settings.execution_poll_seconds)


async def main() -> None:
    # Market prices only (REST) - no WebSocket needed.
    source, adapter = await connected_adapter()
    await asyncio.gather(_execute(adapter), exit_on_source_change(source))


if __name__ == "__main__":
    run_service("execution-engine", main)
