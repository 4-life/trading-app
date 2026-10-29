"""Temporary Keltner backtest (docs/keltner-strategy-engine.md#backtest):
replays the executor's rules over every Keltner paper's stored candles and
replaces its rows in `backtest_trades`. Run after a backfill:

    python -m app.backtest.keltner [YYYY-MM-DD]

Trades start on the given date - the whole history by default.

At each signal candle's close: a Buy opens a long there, a Sell closes it;
a Sell opens a short, a Buy closes it - where the paper's direction allows
(both: either - a close and the opposite entry on the same candle). No
stop-loss. Fees: the selected provider's maker fee on both sides, as for
VWAP."""

import logging
import sys
from datetime import UTC, datetime

from app.backtest.bars import (
    Bar,
    SimTrade,
    load_bars,
    paper_exits,
    save_trades,
    strategy_papers,
    with_paper_exits,
)
from app.backtest.models import OPEN_AT_END
from app.executors.base import direction_allowed
from app.executors.keltner import reason
from app.executors.keltner_signals import KeltnerSignals, keltner_signals
from app.notifications.error_reporting import run_service
from app.papers.models import Paper

logger = logging.getLogger(__name__)


def signals(bars: list[Bar]) -> KeltnerSignals:
    return keltner_signals([b.high for b in bars], [b.low for b in bars], [b.close for b in bars])


def simulate(
    bars: list[Bar], paper_direction: str = "long", start: datetime | None = None
) -> list[SimTrade]:
    """From `start`, one position at a time."""
    ks = signals(bars)
    trades: list[SimTrade] = []
    pos: SimTrade | None = None
    for i, bar in enumerate(bars):
        if start is not None and bar.time < start:
            continue
        signal = ks.at(i)
        if signal is None:
            continue
        if pos is not None and pos.direction != signal:
            pos.closed_at, pos.close_price, pos.exit_reason = bar.time, bar.close, reason(signal)
            trades.append(pos)
            pos = None
        if pos is None and direction_allowed(paper_direction, signal):
            pos = SimTrade(signal, bar.time, bar.close, None, entry_reason=reason(signal))
    if pos is not None and bars:
        pos.closed_at, pos.close_price, pos.exit_reason = bars[-1].time, bars[-1].close, OPEN_AT_END
        trades.append(pos)
    return trades


def simulate_paper(paper: Paper, bars: list[Bar], start: datetime | None = None) -> list[SimTrade]:
    """The strategy's own trades over `bars` - its backtest without saving
    (also the entry signals of an averaging paper's backtest) - cut at the
    paper's own stop-loss / take-profit, if it has them."""
    return with_paper_exits(simulate(bars, paper.direction, start), bars, *paper_exits(paper))


def entry_signals(paper: Paper, bars: list[Bar]) -> list[SimTrade]:
    """Every candle the strategy signals an entry on in the paper's direction
    (both: either) - an entry when flat, held or not (an averaging paper's
    entries and signal adds)."""
    ks = signals(bars)
    out: list[SimTrade] = []
    for i, bar in enumerate(bars):
        signal = ks.at(i)
        if signal is not None and direction_allowed(paper.direction, signal):
            out.append(SimTrade(signal, bar.time, bar.close, None, entry_reason=reason(signal)))
    return out


async def backtest_paper(paper: Paper, start: datetime | None) -> list[SimTrade]:
    bars = await load_bars(paper)
    return await save_trades(paper, simulate_paper(paper, bars, start), bars, start)


async def main() -> None:
    start = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=UTC) if len(sys.argv) > 1 else None
    papers = await strategy_papers("keltner")
    if not papers:
        logger.info("no Keltner papers - nothing to backtest")
    for paper in papers:
        await backtest_paper(paper, start)


if __name__ == "__main__":
    run_service("backtest", main)
