import asyncio
import logging
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from app.config import settings
from app.exchange.base import MarketAdapter
from app.exchange.source import connected_adapter
from app.market_data.collector import FUNDING_COVERAGE_TOLERANCE, backfill_candles, backfill_funding
from app.notifications.error_reporting import run_service
from app.papers.models import REGIME_ASSET
from app.papers.queries import executor_timeframes, paper_asset_timeframes

logger = logging.getLogger(__name__)


async def _backfill_asset(
    adapter: MarketAdapter, asset: str, timeframes: list[str], end: datetime
) -> None:
    t0 = time.monotonic()
    start = end - timedelta(days=settings.backfill_days)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    try:
        candle_counts: dict[str, int] = {}
        for timeframe in timeframes:
            candle_counts[timeframe] = await backfill_candles(
                adapter, asset, timeframe, start_ms, end_ms
            )
        n_funding = await backfill_funding(
            adapter, asset, start_ms, end_ms, coverage_tolerance=FUNDING_COVERAGE_TOLERANCE
        )
    except Exception:
        # One misconfigured/unsupported asset (wrong name, or not a
        # perpetual - see docs/market-data.md) shouldn't block every other,
        # valid asset from backfilling, or the depends_on chain that gates
        # the other services on this one completing.
        logger.exception("backfill failed for %s - skipping it", asset)
        return
    logger.info(
        "backfilled %s: %s, %d funding rows, in %.1fs total",
        asset,
        ", ".join(f"{n} {timeframe} candles" for timeframe, n in candle_counts.items()),
        n_funding,
        time.monotonic() - t0,
    )


async def main() -> None:
    """One-shot historical backfill, run on every `docker compose up` (see
    docs/market-data.md#historical-backfill): candles for every (asset,
    timeframe) of every paper (enabled or disabled), plus funding for those
    assets, over the last BACKFILL_DAYS. Assets backfill concurrently."""
    pairs = await paper_asset_timeframes(enabled_only=False)
    # The trend strategy's bear-market filter reads BTC at each trend paper's
    # timeframe (docs/trend-strategy-engine.md#bear-market-filter).
    pairs = sorted(set(pairs) | {(REGIME_ASSET, tf) for tf in await executor_timeframes("trend")})
    if not pairs:
        logger.info("no papers - nothing to backfill")
        return

    timeframes_by_asset: dict[str, list[str]] = defaultdict(list)
    for asset, timeframe in pairs:
        timeframes_by_asset[asset].append(timeframe)

    # No WebSocket subscriptions happen here - only market-data's live poll
    # loop needs one.
    _, adapter = await connected_adapter()

    unlisted = sorted(a for a in timeframes_by_asset if not adapter.is_listed(a))
    if unlisted:
        logger.warning("not listed by the provider - not backfilled: %s", ", ".join(unlisted))
        for asset in unlisted:
            del timeframes_by_asset[asset]

    end = datetime.now(UTC)
    logger.info(
        "backfilling %d days up to %s: %s",
        settings.backfill_days,
        end.isoformat(),
        ", ".join(f"{a} {'/'.join(tfs)}" for a, tfs in timeframes_by_asset.items()),
    )
    await asyncio.gather(
        *(
            _backfill_asset(adapter, asset, timeframes, end)
            for asset, timeframes in timeframes_by_asset.items()
        )
    )


if __name__ == "__main__":
    run_service("backfill", main)
