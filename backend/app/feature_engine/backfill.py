import asyncio
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import distinct, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult

from app.db import async_session
from app.feature_engine.engine import INTERVAL_MINUTES, compute_features
from app.feature_engine.models import Feature
from app.market_data.models import Candle
from app.notifications.error_reporting import run_service
from app.papers.queries import paper_asset_timeframes

logger = logging.getLogger(__name__)

# Postgres/asyncpg cap bind parameters at 32,767 per query; each row is 5
# params, so 2000 rows/query stays well under it.
INSERT_BATCH_SIZE = 2000

# Log progress every N timestamps, so a long run is distinguishable from a hang.
PROGRESS_LOG_EVERY = 500


async def _flush(rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0
    stmt = pg_insert(Feature).values(rows)
    # Idempotent - backfill reruns on every `up`, and a historical value
    # never changes between runs.
    stmt = stmt.on_conflict_do_nothing(index_elements=["asset", "name", "interval", "computed_at"])
    async with async_session() as session:
        result = await session.execute(stmt)
        await session.commit()
    # Real inserts, not len(rows). session.execute() of an Insert is a
    # CursorResult at runtime.
    return cast(CursorResult[object], result).rowcount


async def _computed_timestamps(
    asset: str, start: datetime, end: datetime, interval: str
) -> set[datetime]:
    """The timestamps that already have features - computed by an earlier
    run. A historical value never changes, so they're done even when some
    feature had no value there (too little history at the start, a zero
    variance): recomputing them would give the same result."""
    async with async_session() as session:
        rows = await session.scalars(
            select(distinct(Feature.computed_at)).where(
                Feature.asset == asset,
                Feature.interval == interval,
                Feature.computed_at >= start,
                Feature.computed_at <= end,
            )
        )
        return set(rows.all())


async def backfill_features(asset: str, start: datetime, end: datetime, interval: str) -> int:
    """Computes and stores historical features for `asset` at `interval`,
    one timestamp per bar across [start, end]. Skips a timestamp an earlier
    run computed (_computed_timestamps). Returns the number of rows inserted."""
    computed = await _computed_timestamps(asset, start, end, interval)
    step = timedelta(minutes=INTERVAL_MINUTES[interval])
    expected_timestamps = max(1, int((end - start) / step) + 1)
    t0 = time.monotonic()
    rows: list[dict[str, object]] = []
    timestamps = 0
    total_rows = 0
    ts = start
    while ts <= end:
        if ts in computed:
            ts += step
            continue
        try:
            # Point-in-time correct: only data at or before `ts` is used.
            values = await compute_features(asset, ts, interval)
        except Exception:
            logger.exception("%s: feature computation failed at %s - skipping it", asset, ts)
            ts += step
            continue
        for name, value in values.items():
            rows.append(
                {
                    "asset": asset,
                    "name": name,
                    "interval": interval,
                    "value": Decimal(str(value)),
                    "computed_at": ts,
                }
            )
        timestamps += 1
        ts += step

        if timestamps % PROGRESS_LOG_EVERY == 0:
            logger.info(
                "%s (%s): %d/%d timestamps processed (%.1fs elapsed)",
                asset,
                interval,
                timestamps,
                expected_timestamps,
                time.monotonic() - t0,
            )

        if len(rows) >= INSERT_BATCH_SIZE:
            total_rows += await _flush(rows)
            rows = []

    total_rows += await _flush(rows)

    if total_rows:
        logger.info(
            "%s (%s): backfilled features at %d timestamps (%d rows) in %.1fs",
            asset,
            interval,
            timestamps,
            total_rows,
            time.monotonic() - t0,
        )
    return total_rows


async def candle_time_range(asset: str, interval: str) -> tuple[datetime, datetime] | None:
    async with async_session() as session:
        earliest = await session.scalar(
            select(Candle.open_time)
            .where(Candle.asset == asset, Candle.interval == interval)
            .order_by(Candle.open_time)
            .limit(1)
        )
        latest = await session.scalar(
            select(Candle.open_time)
            .where(Candle.asset == asset, Candle.interval == interval)
            .order_by(Candle.open_time.desc())
            .limit(1)
        )
    if earliest is None or latest is None:
        return None
    return earliest, latest


async def _backfill_pair(asset: str, timeframe: str) -> None:
    """Never raises - one bad asset shouldn't block the others."""
    try:
        time_range = await candle_time_range(asset, timeframe)
        if time_range is None:
            logger.warning(
                "%s: no %s candles to backfill features from - skipping", asset, timeframe
            )
            return
        start, end = time_range
        await backfill_features(asset, start, end, timeframe)
    except Exception:
        logger.exception("feature backfill failed for %s %s - skipping it", asset, timeframe)


async def main() -> None:
    """Runs after the market-data backfill, for every (asset, timeframe) of
    every paper (enabled or disabled)."""
    pairs = await paper_asset_timeframes(enabled_only=False)
    if not pairs:
        logger.info("no papers - no features to backfill")
        return
    logger.info("backfilling features for %s", ", ".join(f"{a} {tf}" for a, tf in pairs))
    await asyncio.gather(*(_backfill_pair(asset, timeframe) for asset, timeframe in pairs))


if __name__ == "__main__":
    run_service("feature-backfill", main)
