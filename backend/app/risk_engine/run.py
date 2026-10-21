import asyncio

from app.config import settings
from app.exchange.source import connected_adapter, exit_on_source_change
from app.notifications.error_reporting import run_service
from app.risk_engine.service import RiskEngine


async def _run(engine: RiskEngine) -> None:
    while True:
        await engine.run_once()
        await asyncio.sleep(settings.risk_poll_seconds)


async def main() -> None:
    # Market prices only (REST) - no WebSocket needed.
    source, adapter = await connected_adapter()
    await asyncio.gather(_run(RiskEngine(adapter)), exit_on_source_change(source))


if __name__ == "__main__":
    run_service("risk-engine", main)
