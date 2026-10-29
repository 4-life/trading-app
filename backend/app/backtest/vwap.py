"""Temporary VWAP + EMA9 backtest (docs/vwap-strategy-engine.md#backtest):
replays the executor's rules over every VWAP paper's stored candles and
replaces its rows in `backtest_trades`. Run after a backfill:

    python -m app.backtest.vwap [YYYY-MM-DD]

Trades start on the given date - the whole history by default.

At each signal candle's close: the opposite position closes there, and -
flat, direction allowing - the signal's opens there. No stop-loss. Fees:
the selected provider's maker fee on both sides (Hyperliquid without one)."""

import logging
import sys
from datetime import UTC, datetime

from app.backtest.bars import (
    Bar,
    SimTrade,
    exit_at,
    load_bars,
    paper_exits,
    save_trades,
    strategy_papers,
    with_paper_exits,
)
from app.backtest.models import OPEN_AT_END
from app.executors.base import direction_allowed
from app.executors.vwap import reason
from app.executors.vwap_signals import lines, signal_at
from app.notifications.error_reporting import run_service
from app.papers.models import Paper

logger = logging.getLogger(__name__)


def simulate(
    bars: list[Bar], paper_direction: str = "long", start: datetime | None = None
) -> list[SimTrade]:
    """From `start`, one position at a time."""
    closes = [b.close for b in bars]
    ln = lines(
        [b.time for b in bars],
        [b.high for b in bars],
        [b.low for b in bars],
        closes,
        [b.volume for b in bars],
    )
    trades: list[SimTrade] = []
    pos: SimTrade | None = None
    for i, bar in enumerate(bars):
        if start is not None and bar.time < start:
            continue
        signal = signal_at(closes, ln, i)
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
    """Every candle the strategy signals a long on (a short paper: a short;
    both: either) - an entry when flat, held or not (an averaging paper's
    entries and signal adds)."""
    closes = [b.close for b in bars]
    ln = lines(
        [b.time for b in bars],
        [b.high for b in bars],
        [b.low for b in bars],
        closes,
        [b.volume for b in bars],
    )
    signals = [(bar, signal_at(closes, ln, i)) for i, bar in enumerate(bars)]
    return [
        SimTrade(signal, bar.time, bar.close, None, entry_reason=reason(signal))
        for bar, signal in signals
        if signal is not None and direction_allowed(paper.direction, signal)
    ]


def exit_signals(paper: Paper, bars: list[Bar]) -> list[SimTrade]:
    """Every candle the strategy closes a held position on, its own trade
    held or not - as live: a SELL closes a long, a BUY a short (an averaging
    paper's sell signals)."""
    closes = [b.close for b in bars]
    ln = lines(
        [b.time for b in bars],
        [b.high for b in bars],
        [b.low for b in bars],
        closes,
        [b.volume for b in bars],
    )
    out: list[SimTrade] = []
    for i, bar in enumerate(bars):
        signal = signal_at(closes, ln, i)
        if signal is not None:
            out.append(exit_at("short" if signal == "long" else "long", bar, reason(signal)))
    return out


async def backtest_paper(paper: Paper, start: datetime | None) -> list[SimTrade]:
    bars = await load_bars(paper)
    return await save_trades(paper, simulate_paper(paper, bars, start), bars, start)


async def main() -> None:
    start = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=UTC) if len(sys.argv) > 1 else None
    papers = await strategy_papers("vwap")
    if not papers:
        logger.info("no VWAP papers - nothing to backtest")
    for paper in papers:
        await backtest_paper(paper, start)


if __name__ == "__main__":
    run_service("backtest", main)
