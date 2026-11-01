"""The market-shock detector (app/market_data/shocks.py) on stored candles:
every coin's candles loaded, and the shocks of the last hours - for the risk
engine's entry block (docs/risk-engine.md) and the strategy chart."""

import asyncio
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.market_data.models import Candle
from app.market_data.shocks import Series, Shock, lookback, market_shocks

# The detector's own timeframe - finer than any paper's: an event shows within a minute.
SHOCK_INTERVAL = "1m"
SHOCK_STEP = timedelta(minutes=1)
# Recent shocks are recomputed at most this often (each loads every coin's 1m candles).
REFRESH_SECONDS = 60

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


def blocking(shocks: list[Shock], direction: str) -> Shock | None:
    """The shock that holds back an entry in `direction`: a panic a long, a
    bullrun a short (the market's or the coin's own) - the latest."""
    against = "panic" if direction == "long" else "bullrun"
    hits = [s for s in shocks if s.kind == against]
    return hits[-1] if hits else None
