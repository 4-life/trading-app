"""Temporary Keltner backtest (docs/keltner-strategy-engine.md#backtest):
replays the executor's rules over every Keltner paper's stored candles and
replaces its rows in `backtest_trades`. Run after a backfill:

    python -m app.backtest.keltner [YYYY-MM-DD]

Trades start on the given date - the whole history by default.

At each signal candle's close: the paper's opening signal (Buy for a long
paper, Sell for a short one) opens the position there, the opposite one
closes it there. No stop-loss. Fees: the selected provider's maker fee on
both sides, as for VWAP."""

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
from app.executors.keltner import KELTNER_BUY, KELTNER_SELL
from app.executors.keltner_signals import KeltnerSignals, keltner_signals
from app.notifications.error_reporting import run_service
from app.order_queue import Direction
from app.papers.models import Paper

logger = logging.getLogger(__name__)


def signals(bars: list[Bar]) -> KeltnerSignals:
    return keltner_signals([b.high for b in bars], [b.low for b in bars], [b.close for b in bars])


def simulate(
    bars: list[Bar], direction: Direction = "long", start: datetime | None = None
) -> list[SimTrade]:
    """From `start`, one position at a time."""
    ks = signals(bars)
    long = direction == "long"
    opens, closes = (ks.buy, ks.sell) if long else (ks.sell, ks.buy)
    entry, exit_ = (KELTNER_BUY, KELTNER_SELL) if long else (KELTNER_SELL, KELTNER_BUY)
    trades: list[SimTrade] = []
    pos: SimTrade | None = None
    for i, bar in enumerate(bars):
        if start is not None and bar.time < start:
            continue
        if pos is not None and closes[i]:
            pos.closed_at, pos.close_price, pos.exit_reason = bar.time, bar.close, exit_
            trades.append(pos)
            pos = None
        elif pos is None and opens[i]:
            pos = SimTrade(direction, bar.time, bar.close, None, entry_reason=entry)
    if pos is not None and bars:
        pos.closed_at, pos.close_price, pos.exit_reason = bars[-1].time, bars[-1].close, OPEN_AT_END
        trades.append(pos)
    return trades


def _direction(paper: Paper) -> Direction:
    return "long" if paper.direction == "long" else "short"


def simulate_paper(paper: Paper, bars: list[Bar], start: datetime | None = None) -> list[SimTrade]:
    """The strategy's own trades over `bars` - its backtest without saving
    (also the entry signals of an averaging paper's backtest) - cut at the
    paper's own stop-loss / take-profit, if it has them."""
    return with_paper_exits(simulate(bars, _direction(paper), start), bars, *paper_exits(paper))


def entry_signals(paper: Paper, bars: list[Bar]) -> list[SimTrade]:
    """Every candle the strategy signals an entry on in the paper's direction
    - an entry when flat, held or not (an averaging paper's entries and
    signal adds)."""
    direction = _direction(paper)
    ks = signals(bars)
    opens, reason = (ks.buy, KELTNER_BUY) if direction == "long" else (ks.sell, KELTNER_SELL)
    return [
        SimTrade(direction, bar.time, bar.close, None, entry_reason=reason)
        for i, bar in enumerate(bars)
        if opens[i]
    ]


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
