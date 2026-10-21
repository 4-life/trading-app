"""Temporary Bull Run Catch backtest (docs/bullrun-strategy-engine.md#backtest):
replays the executor's rules over every Bull Run Catch paper's stored candles
and replaces its rows in `backtest_trades`. Run after a backfill:

    python -m app.backtest.bullrun [YYYY-MM-DD]

Trades start on the given date - the whole history by default.

Candle-level approximation of the live executor (which checks the latest
trade every 5 s): flat, a candle closing a pullback in an uptrend opens a
long at its close - in a downtrend, a short (mirrored). The stop for a
candle comes from the candles closed before it (break-even and trailing
stop alike); a candle trading through it closes the position at the stop -
at the open if it opened past it - and fills STOP_SLIPPAGE further. The
same candle may open the next position at its close. Fees: the selected
provider's maker fee on both sides, as for VWAP."""

import logging
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.backtest.bars import STOP_SLIPPAGE, Bar, SimTrade, load_bars, save_trades
from app.backtest.models import OPEN_AT_END
from app.db import async_session
from app.executors.base import direction_allowed
from app.executors.bullrun import PULLBACK_ENTRY, Side, entry_stop, exit_stop, side
from app.notifications.error_reporting import run_service
from app.order_queue import Direction
from app.papers.models import Paper

logger = logging.getLogger(__name__)


def simulate(
    bars: list[Bar],
    timeframe: str,
    directions: tuple[Direction, ...] = ("long",),
    start: datetime | None = None,
    stop_slippage: float = 0.0,
) -> list[SimTrade]:
    """From `start`, one position at a time. `stop_slippage`: each stop fills
    that far past its price."""
    times = [b.time for b in bars]
    highs, lows, closes = [b.high for b in bars], [b.low for b in bars], [b.close for b in bars]
    sides = [side(d, times, highs, lows, closes, timeframe) for d in directions]
    trades: list[SimTrade] = []
    held: tuple[SimTrade, Side] | None = None
    best: float | None = None  # the side's highest high of the candles closed since entry
    for i, bar in enumerate(bars):
        if held is not None:
            pos, s = held
            assert pos.stop_loss_price is not None  # Bull Run trades always have one
            stop, reason = exit_stop(
                s.sign * pos.entry_price, s.sign * pos.stop_loss_price, best, s.ind.atr[i - 1]
            )
            if s.lows[i] <= stop:
                pos.closed_at, pos.exit_reason = bar.time, reason
                fill = s.sign * min(s.sign * bar.open, stop)
                pos.close_price = fill * (1 - s.sign * stop_slippage)
                trades.append(pos)
                held = None
            else:
                best = s.highs[i] if best is None else max(best, s.highs[i])
                continue
        if start is not None and bar.time < start:
            continue
        for s in sides:
            initial = entry_stop(s.highs, s.lows, s.closes, s.ind, i)
            if initial is not None:
                pos = SimTrade(
                    s.direction, bar.time, bar.close, s.sign * initial, entry_reason=PULLBACK_ENTRY
                )
                held, best = (pos, s), None
                break
    if held is not None:
        pos = held[0]
        pos.closed_at, pos.close_price, pos.exit_reason = bars[-1].time, bars[-1].close, OPEN_AT_END
        trades.append(pos)
    return trades


async def backtest_paper(paper: Paper, start: datetime | None) -> list[SimTrade]:
    bars = await load_bars(paper)
    both: tuple[Direction, ...] = ("long", "short")
    directions = tuple(d for d in both if direction_allowed(paper.direction, d))
    simulated = simulate(bars, paper.timeframe, directions, start, stop_slippage=STOP_SLIPPAGE)
    return await save_trades(paper, simulated, bars, start)


async def main() -> None:
    start = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=UTC) if len(sys.argv) > 1 else None
    async with async_session() as session:
        papers = (await session.scalars(select(Paper).where(Paper.executor == "bullrun"))).all()
    if not papers:
        logger.info("no Bull Run Catch papers - nothing to backtest")
    for paper in papers:
        await backtest_paper(paper, start)


if __name__ == "__main__":
    run_service("backtest", main)
