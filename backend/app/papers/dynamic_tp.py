"""A Keltner averaging paper's dynamic take-profit (docs/papers.md#dynamic-take-profit):
the average move of its last DAYS' cycles, from a good entry to a good sell
(app/executors/keltner_averaging.py average_cycle_move), for each paper once per
EVERY. For looking at only: nothing trades on it. Stored as a share of the price
- the dashboard multiplies it by the paper's leverage, whichever that is by then.

Runs as a loop in the market-data service, like the preparation."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import or_, select, update

from app.db import async_session
from app.executors.base import recent_candles
from app.executors.keltner import CANDLE_LOOKBACK
from app.executors.keltner_averaging import average_cycle_move, keltner_guard
from app.feature_engine.engine import INTERVAL_MINUTES
from app.market_data.models import Candle
from app.papers.models import Paper

logger = logging.getLogger(__name__)

DAYS = 30
EVERY = timedelta(hours=24)
POLL_SECONDS = 300


def measure(paper_direction: str, candles: list[Candle]) -> tuple[float | None, int]:
    """Over the DAYS before the last candle - CPU-bound."""
    if not candles:
        return None, 0
    guard = keltner_guard(
        paper_direction,
        [float(c.high) for c in candles],
        [float(c.low) for c in candles],
        [float(c.close) for c in candles],
    )
    times = [c.open_time for c in candles]
    return average_cycle_move(guard, times, times[-1] - timedelta(days=DAYS))


async def _refresh(paper: Paper) -> None:
    per_day = 24 * 60 // INTERVAL_MINUTES[paper.timeframe]
    candles = await recent_candles(paper.asset, paper.timeframe, DAYS * per_day + CANDLE_LOOKBACK)
    move, cycles = await asyncio.to_thread(measure, paper.direction, candles)
    async with async_session() as session, session.begin():
        await session.execute(
            update(Paper)
            .where(Paper.id == paper.id)
            .values(
                dynamic_tp_move=None if move is None else Decimal(str(round(move, 6))),
                dynamic_tp_cycles=cycles,
                dynamic_tp_at=datetime.now(UTC),
            )
        )
    logger.info("paper %d: dynamic take-profit move %s over %d cycles", paper.id, move, cycles)


async def run_dynamic_tp_loop() -> None:
    """Every Keltner averaging paper that's ready, the oldest value first."""
    while True:
        try:
            async with async_session() as session:
                papers = (
                    await session.scalars(
                        select(Paper)
                        .where(
                            Paper.kind == "averaging",
                            Paper.executor == "keltner",
                            Paper.prep_status.is_(None),
                            or_(
                                Paper.dynamic_tp_at.is_(None),
                                Paper.dynamic_tp_at <= datetime.now(UTC) - EVERY,
                            ),
                        )
                        .order_by(Paper.dynamic_tp_at.nulls_first(), Paper.id)
                    )
                ).all()
            for paper in papers:
                await _refresh(paper)
        except Exception:
            logger.exception("dynamic take-profit loop failed")
        await asyncio.sleep(POLL_SECONDS)
