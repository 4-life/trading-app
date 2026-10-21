import asyncio

from app.config import settings
from app.exchange.source import connected_adapter, exit_on_source_change
from app.market_data.collector import MarketDataCollector
from app.market_data.limits import refresh_market_limits
from app.notifications.error_reporting import run_service
from app.papers.prep import run_prep_loop


async def main() -> None:
    source, adapter = await connected_adapter(skip_ws=False)
    await refresh_market_limits(source.provider, adapter)
    collector = MarketDataCollector(adapter, settings.assets)
    # New papers are backfilled / backtested here (docs/papers.md#preparation).
    await asyncio.gather(collector.start(), run_prep_loop(adapter), exit_on_source_change(source))


if __name__ == "__main__":
    run_service("market-data", main)
