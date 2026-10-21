"""Regime strategy executor: holds the BigBeluga trend - a trend-band flip
(or a band break signal while the trend holds) opens the position; the
opposite flip closes it (a flip reverses on the same candle for direction both).
A short also closes at the bottom - a confirmed HH - and a reversal long
opens there, stop under the sell-off's low; stopped (or a new 4h LL) before
the bands turn bullish - a false bottom - it's re-bought at each new 4h LL,
stop under it, and no short opens meanwhile. A long also closes when a
candle touches the last 4h HH confirmed since its entry and closes under
it, or when a 4h LL is confirmed since its entry. A DISASTER_STOP far from
the entry stays below liquidation. For low leverage (2-3x) - see
docs/regime-strategy-engine.md.
Run: python -m app.executors.regime"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.api.portfolio import exit_levels
from app.executors.base import (
    Tick,
    direction_allowed,
    last_entry_at,
    last_placed_decision,
    live_trade_price,
    recent_candles,
    run,
)
from app.executors.bullrun import EPOCH
from app.executors.swings import Swing, find_swings
from app.executors.trend_bands import ATR_LENGTH, CALC_BARS, Bands, trend_bands
from app.feature_engine.engine import INTERVAL_MINUTES
from app.notifications.error_reporting import run_service
from app.order_queue import Direction, Signal
from app.papers.models import Paper

DISASTER_STOP = 0.10  # from the entry: 30% of margin at 3x, before liquidation
REBUY_BUFFER_ATR = 0.5  # a re-buy's stop this many ATRs (100) under its 4h LL: not at the LL
HIGHER_TIMEFRAME = "4h"  # the swings of the re-buys and the long exits

REGIME_ENTRY = "regime_entry"  # either direction
REVERSAL_ENTRY = "reversal_entry"  # the long opened at a short's bottom exit
LL_REBUY = "ll_rebuy"  # after a false bottom: the long re-bought at a new 4h LL
REVERSAL_REASONS = (REVERSAL_ENTRY, LL_REBUY)  # the longs with a false-bottom stop
DISASTER_EXIT = "disaster_stop"
BOTTOM_EXIT = "bottom_exit"  # a short closed: an HH confirmed since its entry
FALSE_BOTTOM_EXIT = "false_bottom"  # a reversal long stopped before the bands turned bullish
HH_REJECTION_EXIT = "hh_rejection"  # a long closed: the last 4h HH touched, closed under
TOP_EXIT = "top_exit"  # a long closed: a 4h LL confirmed since its entry
REGIME_EXIT = "regime_flip"  # the trend bands left the trade's regime


@dataclass(frozen=True)
class View:
    """One direction's view of the candles. The rules are written for a long;
    a short is a long on the negated prices (highs and lows swapped), so
    `sign` x a real price is a price in this view and back - every indicator
    here mirrors under negation."""

    direction: Direction
    sign: int
    highs: list[float]
    lows: list[float]
    closes: list[float]
    bands: Bands
    swings: list[Swing]


def view(
    direction: Direction,
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> View:
    if direction == "short":
        highs, lows, closes = [-x for x in lows], [-x for x in highs], [-x for x in closes]
    return View(
        direction,
        1 if direction == "long" else -1,
        highs,
        lows,
        closes,
        trend_bands(highs, lows, closes, volumes),
        find_swings(highs, lows),
    )


def trend_signal(v: View, i: int) -> bool:
    """Candle `i` starts or continues a bullish run: the trend bands flip
    bullish on its close, or a band break-up while bullish."""
    state = v.bands.state
    return i > 0 and state[i] == 1 and (state[i - 1] != 1 or v.bands.break_up[i])


def disaster_stop(entry: float) -> float:
    """A long's stop for an entry at `entry` - in a View's prices (a short's negated)."""
    return entry - DISASTER_STOP * abs(entry)


def higher_swings(
    times: list[datetime], highs: list[float], lows: list[float], timeframe: str
) -> list[Swing]:
    """find_swings on HIGHER_TIMEFRAME candles built from the paper's (UTC
    boundaries, complete ones only; the paper's own at that timeframe).
    Indices are the paper's candles: the higher candle's first one as the
    pivot, the one closing the confirming higher candle as the confirmation."""
    step = timedelta(minutes=INTERVAL_MINUTES[timeframe])
    higher = timedelta(minutes=INTERVAL_MINUTES[HIGHER_TIMEFRAME])
    if higher <= step:
        return find_swings(highs, lows)
    per = higher // step
    groups = [
        (k - per + 1, k)
        for k, t in enumerate(times)
        if (t + step - EPOCH) % higher == timedelta(0)
        and k >= per - 1
        and times[k - per + 1] == t - (per - 1) * step
    ]
    swings = find_swings(
        [max(highs[a : b + 1]) for a, b in groups], [min(lows[a : b + 1]) for a, b in groups]
    )
    return [
        Swing(s.kind, s.price, groups[s.pivot_index][0], groups[s.confirm_index][1]) for s in swings
    ]


def reversal_stop(v: View, short_entry_index: int, i: int, entry: float) -> float:
    """A long's view: the reversal long's stop for an entry at `entry` after
    candle `i` - under the lowest low since the short's entry candle, at most
    the disaster stop away."""
    return max(min(v.lows[short_entry_index : i + 1]), disaster_stop(entry))


def _never_bullish(v: View, entry_index: int, i: int) -> bool:
    return all(v.bands.state[k] != 1 for k in range(entry_index, i + 1))


def held_stop(
    v: View, recorded: float, entry: float, reversal: bool, entry_index: int, i: int
) -> tuple[float, str]:
    """An open position's stop after candle `i`'s close (in `v`'s prices) and
    the exit reason it closes with: a reversal long's recorded stop until the
    bands turn bullish, else the disaster stop."""
    if reversal and _never_bullish(v, entry_index, i):
        return recorded, FALSE_BOTTOM_EXIT
    return disaster_stop(entry), DISASTER_EXIT


def exit_reason(
    v: View, higher: list[Swing], entry_index: int, i: int, reversal: bool = False
) -> str | None:
    """At candle `i`'s close, a position (in `v`'s direction) opened at candle
    `entry_index`'s close; `higher`: the 4h swings in real prices.
    - REGIME_EXIT: the regime left bullish after being bullish since the entry.
    - A short's BOTTOM_EXIT: an LL in its view (an HH) confirmed since the entry.
    - A long's HH_REJECTION_EXIT: candle `i` reaches the last 4h HH confirmed
      since the entry (before `i`) and closes under it.
    - A long's TOP_EXIT: a 4h LL confirmed since the entry - for a `reversal`
      long before the bands turned bullish, FALSE_BOTTOM_EXIT."""
    state = v.bands.state
    never_bullish = _never_bullish(v, entry_index, i)
    if state[i] != 1 and not never_bullish:
        return REGIME_EXIT
    if v.direction == "short":
        bottom = any(s.kind == "LL" and entry_index < s.confirm_index <= i for s in v.swings)
        if bottom:
            return BOTTOM_EXIT
    else:
        hhs = [s for s in higher if s.kind == "HH" and entry_index < s.confirm_index < i]
        if hhs and v.highs[i] >= hhs[-1].price > v.closes[i]:
            return HH_REJECTION_EXIT
        if any(s.kind == "LL" and entry_index < s.confirm_index <= i for s in higher):
            return FALSE_BOTTOM_EXIT if reversal and never_bullish else TOP_EXIT
    return None


def rebuy_level(v: View, higher: list[Swing], i: int) -> float | None:
    """A long's view, after a false bottom: a 4h LL confirmed at candle `i`'s
    close with the close above it and the bands not bullish - the re-buy's
    stop (REBUY_BUFFER_ATR under the LL), else None."""
    a = v.bands.atr[i]
    if v.bands.state[i] == 1 or a is None:
        return None
    lls = [s for s in higher if s.kind == "LL" and s.confirm_index == i]
    if not lls or v.closes[i] <= lls[-1].price:
        return None
    return lls[-1].price - REBUY_BUFFER_ATR * a


class RegimeStrategy:
    name = "regime"

    async def before_poll(self, papers: list[Paper], poll_started_at: datetime) -> None:
        return None

    async def decide(self, tick: Tick) -> Signal | None:
        paper, position = tick.paper, tick.position
        candles = await recent_candles(paper.asset, paper.timeframe, CALC_BARS)
        if len(candles) <= ATR_LENGTH:
            return None
        times = [c.open_time for c in candles]
        series = (
            [float(c.high) for c in candles],
            [float(c.low) for c in candles],
            [float(c.close) for c in candles],
            [float(c.volume) for c in candles],
        )
        higher = higher_swings(times, series[0], series[1], paper.timeframe)
        price = float(await live_trade_price(paper.asset) or tick.price)
        step = timedelta(minutes=INTERVAL_MINUTES[paper.timeframe])
        last = len(candles) - 1
        latest = await last_placed_decision(paper)  # an open position's: its entry
        if position is not None:
            held: Direction = "long" if position.direction == "long" else "short"
            v = view(held, *series)
            # The entry candle: the last one closed by the entry.
            after = [k for k, t in enumerate(times) if t + step > position.opened_at]
            entry_index = max(after[0] - 1, 0) if after else last
            entry = v.sign * float(position.entry_price)
            recorded = (await exit_levels([position.id])).get(position.id, (None, None))[0]
            reversal = latest is not None and latest.reason in REVERSAL_REASONS
            stop, reason = held_stop(
                v,
                v.sign * float(recorded) if recorded else disaster_stop(entry),
                entry,
                reversal,
                entry_index,
                last,
            )
            if v.sign * price <= stop:
                return Signal("exit", held, reason)
            closed = exit_reason(v, higher, entry_index, last, reversal)
            return Signal("exit", held, closed) if closed else None
        this_candle = times[-1] + step  # decided after the last candle's close
        false_bottom = latest is not None and latest.reason == FALSE_BOTTOM_EXIT
        directions: tuple[Direction, ...] = ("long", "short")
        for direction in directions:
            if not direction_allowed(paper.direction, direction):
                continue
            if direction == "short" and false_bottom:
                continue  # waiting for the re-buy, not shorting
            v = view(direction, *series)
            entry_reason, stop = None, disaster_stop(v.sign * price)
            if trend_signal(v, last):
                entry_reason = REGIME_ENTRY
            elif direction == "long" and latest is not None:
                level = rebuy_level(v, higher, last) if false_bottom else None
                if latest.reason == BOTTOM_EXIT and latest.decided_at >= this_candle:
                    # The short's entry candle: the last one closed by its entry.
                    opened = await last_entry_at(paper, direction="short")
                    before = [k for k, t in enumerate(times) if opened and t + step <= opened]
                    entry_reason = REVERSAL_ENTRY
                    stop = reversal_stop(v, before[-1] if before else 0, last, price)
                elif level is not None:
                    entry_reason, stop = LL_REBUY, level
            if entry_reason is None or v.sign * price <= stop:
                continue
            last_entry = await last_entry_at(paper, direction=direction)
            if last_entry is not None and last_entry >= this_candle:
                return None  # one entry per signal candle
            return Signal(
                "enter", direction, entry_reason, stop_loss_price=Decimal(str(v.sign * stop))
            )
        return None


if __name__ == "__main__":
    run_service("regime-executor", lambda: run(RegimeStrategy()))
