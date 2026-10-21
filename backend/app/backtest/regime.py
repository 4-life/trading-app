"""Temporary Regime backtest (docs/regime-strategy-engine.md#backtest):
replays the executor's rules over every Regime paper's stored candles and
replaces its rows in `backtest_trades`. Run after a backfill:

    python -m app.backtest.regime [YYYY-MM-DD]

Trades start on the given date - the whole history by default.

Candle-level approximation of the live executor: an entry candle opens the
position at its close. A candle trading through the stop (from the candles
closed before it) closes the position there - at the open if it opened past
it - filling STOP_SLIPPAGE further; otherwise an exit at its close closes it
at that close: a short's bottom exit opens the reversal long there, a regime
flip lets the same candle open the opposite position (direction allowing).
After a false bottom, no short opens until a long does. Fees: the selected
provider's maker fee on both sides, as for VWAP.

Temporary pyramiding test (backtest only - the execution engine has one
entry per position): a long adds an equal unit at each close above a 4h
HH confirmed since its entry (one add per HH, up to MAX_UNITS); each add
moves every unit's stop under the last 4h HL; all units close together.
Each unit is stored as its own trade."""

import logging
import sys
from datetime import UTC, datetime

from app.backtest.bars import (
    STOP_SLIPPAGE,
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
from app.executors.regime import (
    BOTTOM_EXIT,
    FALSE_BOTTOM_EXIT,
    LL_REBUY,
    REGIME_ENTRY,
    REVERSAL_ENTRY,
    REVERSAL_REASONS,
    View,
    disaster_stop,
    exit_reason,
    held_stop,
    higher_swings,
    rebuy_level,
    reversal_stop,
    trend_signal,
    view,
)
from app.executors.swings import Swing
from app.notifications.error_reporting import run_service
from app.order_queue import Direction
from app.papers.models import Paper

logger = logging.getLogger(__name__)

MAX_UNITS = 3  # the first entry and up to two adds
PYRAMID_ADD = "pyramid_add"
PYRAMID_STOP_EXIT = "pyramid_stop"  # under the last 4h HL, set at each add


def pyramid_add(v: View, higher: list[Swing], entry_index: int, i: int) -> Swing | None:
    """A long's view, opened at candle `entry_index`: the last 4h HH confirmed
    since then (before `i`) if candle `i` closes above it with the bands
    bullish - the trend broke its high: the add. Else None. (A HH can't be
    broken when it's confirmed: the candles confirming it stay under it.)"""
    if v.direction != "long" or v.bands.state[i] != 1:
        return None
    hhs = [s for s in higher if s.kind == "HH" and entry_index < s.confirm_index < i]
    return hhs[-1] if hhs and v.closes[i] > hhs[-1].price else None


def pyramid_stop(higher: list[Swing], i: int, stop: float | None) -> float | None:
    """The units' stop after an add at candle `i`: under the last 4h HL
    confirmed by then, never lower than `stop`."""
    hls = [s.price for s in higher if s.kind == "HL" and s.confirm_index <= i]
    if not hls:
        return stop
    return hls[-1] if stop is None else max(stop, hls[-1])


def simulate(
    bars: list[Bar],
    timeframe: str,
    directions: tuple[Direction, ...] = ("long",),
    start: datetime | None = None,
    stop_slippage: float = 0.0,
) -> list[SimTrade]:
    """From `start`, one position at a time. `stop_slippage`: each stop fills
    that far past its price."""
    series = (
        [b.high for b in bars],
        [b.low for b in bars],
        [b.close for b in bars],
        [b.volume for b in bars],
    )
    views = {d: view(d, *series) for d in directions}
    higher = higher_swings([b.time for b in bars], series[0], series[1], timeframe)
    trades: list[SimTrade] = []
    held: tuple[SimTrade, View, int] | None = None  # the position, its view, its entry candle
    adds: list[SimTrade] = []  # the held long's pyramid units after the first
    added_stop: float | None = None  # their stop, set at each add
    added_on: set[int] = set()  # the 4h HHs (pivot candles) already added on
    false_bottom = False  # since the last false bottom, no long has opened

    def close_all(pos: SimTrade, at: datetime, price: float, reason: str) -> None:
        nonlocal adds, added_stop
        for unit in (pos, *adds):
            unit.closed_at, unit.close_price, unit.exit_reason = at, price, reason
            trades.append(unit)
        adds, added_stop = [], None

    def open_at(i: int, v: View, reason: str, stop: float) -> tuple[SimTrade, View, int]:
        return SimTrade(v.direction, bars[i].time, bars[i].close, stop, entry_reason=reason), v, i

    for i, bar in enumerate(bars):
        if held is not None:
            pos, v, entry_index = held
            assert pos.stop_loss_price is not None  # Regime trades always have one
            entry = v.sign * pos.entry_price
            reversal = pos.entry_reason in REVERSAL_REASONS
            stop, reason = held_stop(
                v, v.sign * pos.stop_loss_price, entry, reversal, entry_index, i - 1
            )
            if added_stop is not None and added_stop > stop:
                stop, reason = added_stop, PYRAMID_STOP_EXIT
            if v.lows[i] <= stop:
                fill = v.sign * min(v.sign * bar.open, stop)
                close_all(pos, bar.time, fill * (1 - v.sign * stop_slippage), reason)
            else:
                closed = exit_reason(v, higher, entry_index, i, reversal)
                if closed is None:
                    hh = pyramid_add(v, higher, entry_index, i)
                    if len(adds) + 1 < MAX_UNITS and hh and hh.pivot_index not in added_on:
                        added_on.add(hh.pivot_index)
                        added_stop = pyramid_stop(higher, i, added_stop)
                        unit_stop = stop if added_stop is None else max(stop, added_stop)
                        unit = SimTrade("long", bar.time, bar.close, unit_stop)
                        unit.entry_reason = PYRAMID_ADD
                        adds.append(unit)
                    continue
                reason = closed
                close_all(pos, bar.time, bar.close, reason)
            held = None
            false_bottom = false_bottom or reason == FALSE_BOTTOM_EXIT
            if reason == BOTTOM_EXIT and "long" in views:
                stop = reversal_stop(views["long"], entry_index, i, bar.close)
                held = open_at(i, views["long"], REVERSAL_ENTRY, stop)
                continue
        if start is not None and bar.time < start:
            continue
        for d, v in views.items():
            if d == "short" and false_bottom:
                continue
            if trend_signal(v, i):
                held = open_at(i, v, REGIME_ENTRY, v.sign * disaster_stop(v.sign * bar.close))
            elif d == "long" and false_bottom:
                level = rebuy_level(v, higher, i)
                if level is None:
                    continue
                held = open_at(i, v, LL_REBUY, level)
            else:
                continue
            false_bottom = false_bottom and d != "long"
            break
    if held is not None:
        close_all(held[0], bars[-1].time, bars[-1].close, OPEN_AT_END)
    return trades


def simulate_paper(paper: Paper, bars: list[Bar], start: datetime | None = None) -> list[SimTrade]:
    """The strategy's own trades over `bars` - its backtest without saving
    (also the entry signals of an averaging paper's backtest) - cut at the
    paper's own stop-loss / take-profit, if it has them."""
    both: tuple[Direction, ...] = ("long", "short")
    directions = tuple(d for d in both if direction_allowed(paper.direction, d))
    trades = simulate(bars, paper.timeframe, directions, start, stop_slippage=STOP_SLIPPAGE)
    return with_paper_exits(trades, bars, *paper_exits(paper))


def entry_signals(paper: Paper, bars: list[Bar]) -> list[SimTrade]:
    """Every candle the trend signals a long on - held or not (an averaging
    paper's entries and signal adds; its other entries come from its trades)."""
    if not direction_allowed(paper.direction, "long"):
        return []
    v = view(
        "long",
        [b.high for b in bars],
        [b.low for b in bars],
        [b.close for b in bars],
        [b.volume for b in bars],
    )
    return [
        SimTrade("long", bar.time, bar.close, None, entry_reason=REGIME_ENTRY)
        for i, bar in enumerate(bars)
        if trend_signal(v, i)
    ]


async def backtest_paper(paper: Paper, start: datetime | None) -> list[SimTrade]:
    bars = await load_bars(paper)
    return await save_trades(paper, simulate_paper(paper, bars, start), bars, start)


async def main() -> None:
    start = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=UTC) if len(sys.argv) > 1 else None
    papers = await strategy_papers("regime")
    if not papers:
        logger.info("no Regime papers - nothing to backtest")
    for paper in papers:
        await backtest_paper(paper, start)


if __name__ == "__main__":
    run_service("backtest", main)
