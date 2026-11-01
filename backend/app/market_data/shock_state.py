"""The market-shock detector (app/market_data/shocks.py) on stored candles,
and the entry block after a shock (docs/market-shocks.md): the same for the
strategy chart, the backtests and the risk engine."""

import asyncio
import time
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.feature_engine.engine import INTERVAL_MINUTES
from app.market_data.models import Candle
from app.market_data.shocks import Series, Shock, lookback, market_shocks
from app.papers.models import REGIME_ASSET

# The detector's own timeframe - finer than any paper's: an event shows within a minute.
SHOCK_INTERVAL = "1m"
SHOCK_STEP = timedelta(minutes=1)
# Recent shocks are recomputed at most this often (each loads every coin's 1m candles).
REFRESH_SECONDS = 60
# How far back the 1m detection reaches (every coin's 1m candles are a lot of rows).
SHOCK_FINE_SPAN = timedelta(days=14)
# 1m candles over this much before an event: the 1m detection saw it (else
# the timeframe's does).
SHOCK_COVERAGE = timedelta(hours=4)
# A shock holds back the entries against it this long: a panic the longs, a
# bullrun the shorts - the market's, or the coin's own.
SHOCK_BLOCK = timedelta(hours=6)

_recent: dict[tuple[str, timedelta], tuple[float, list[Shock]]] = {}


async def load_series(
    session: AsyncSession, interval: str, since: datetime, before: datetime
) -> dict[str, Series]:
    """Every coin's candles at `interval` from `since` to before `before`."""
    rows = await session.execute(
        select(Candle.asset, Candle.open_time, Candle.close, Candle.volume).where(
            Candle.interval == interval,
            Candle.open_time >= since,
            Candle.open_time < before,
        )
    )
    series: dict[str, Series] = defaultdict(dict)
    for asset, open_time, close, volume in rows.all():
        series[asset][open_time] = (float(close), float(volume))
    return series


async def detect(
    session: AsyncSession, asset: str, timeframe: str, first: datetime, end: datetime
) -> list[Shock]:
    """The shocks on `asset` (the market's, its own) from `first` to `end`,
    oldest first: from every coin's 1m candles (lookback() more before) over
    the last SHOCK_FINE_SPAN; where BTC's 1m candles don't cover the hours
    before an event (before that span, before they were collected, a gap
    while market-data was down), from the `timeframe`'s candles."""
    step = timedelta(minutes=INTERVAL_MINUTES[timeframe])
    fine_start = max(first, end - SHOCK_FINE_SPAN)
    minutes = await load_series(
        session, SHOCK_INTERVAL, fine_start - lookback(SHOCK_STEP) * SHOCK_STEP, end
    )
    found = await asyncio.to_thread(market_shocks, minutes, asset, SHOCK_STEP, fine_start)
    btc = minutes.get(REGIME_ASSET, {})

    def covered(at: datetime) -> bool:
        """BTC's 1m candles cover the SHOCK_COVERAGE before `at`'s candle closed."""
        if at < fine_start:
            return False
        span = SHOCK_COVERAGE // SHOCK_STEP
        known = sum(1 for k in range(span) if at + step - (k + 1) * SHOCK_STEP in btc)
        return known >= span * 0.9

    coarse = await load_series(session, timeframe, first - lookback(step) * step, end)
    older = await asyncio.to_thread(market_shocks, coarse, asset, step, first)
    found = [*found, *(s for s in older if not covered(s.time))]
    return sorted((s for s in found if s.time >= first), key=lambda s: s.time)


def entry_blocked(shocks: Sequence[Shock], direction: str, at: datetime) -> Shock | None:
    """The shock holding back an entry in `direction` at `at`: a panic a long,
    a bullrun a short, detected at or before `at` within SHOCK_BLOCK - the latest."""
    against = "panic" if direction == "long" else "bullrun"
    hits = [
        s for s in shocks if s.kind == against and s.detected_at <= at < s.detected_at + SHOCK_BLOCK
    ]
    return hits[-1] if hits else None


async def recent_shocks(asset: str, span: timedelta) -> list[Shock]:
    """The shocks on `asset` (the market's, its own) detected within the last
    `span`, from every coin's closed 1m candles - cached REFRESH_SECONDS."""
    cached = _recent.get((asset, span))
    if cached is not None and time.monotonic() - cached[0] < REFRESH_SECONDS:
        return cached[1]
    now = datetime.now(UTC)
    closed_before = now - SHOCK_STEP  # the forming 1m candle left out
    start = now - span - SHOCK_STEP
    async with async_session() as session:
        series = await load_series(
            session, SHOCK_INTERVAL, start - lookback(SHOCK_STEP) * SHOCK_STEP, closed_before
        )
    found = await asyncio.to_thread(market_shocks, series, asset, SHOCK_STEP, start)
    shocks = [s for s in found if s.detected_at >= now - span]
    _recent[(asset, span)] = (time.monotonic(), shocks)
    return shocks
