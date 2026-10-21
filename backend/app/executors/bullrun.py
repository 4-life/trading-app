"""Bull Run Catch strategy executor: buys the pullback in an uptrend (on the
paper's timeframe and the next higher one) with a cheap stop under the
pullback, moves the stop to break-even at +1R, then trails it 3 x ATR under
the highest high - no take-profit; shorts the rally in a downtrend the same
way, mirrored - see docs/bullrun-strategy-engine.md.
Run: python -m app.executors.bullrun"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.api.portfolio import exit_levels
from app.executors.base import (
    Tick,
    direction_allowed,
    last_entry_at,
    live_trade_price,
    recent_candles,
    run,
)
from app.feature_engine.engine import INTERVAL_MINUTES
from app.notifications.error_reporting import run_service
from app.order_queue import Direction, Signal
from app.papers.models import Paper

CANDLE_LOOKBACK = 1000  # the slow EMA's warm-up + the highest high since entry
FAST_EMA, MID_EMA, SLOW_EMA = 20, 50, 200
# The higher timeframe's trend: built from the paper's own candles.
HIGHER_TIMEFRAME = {"1h": "4h", "4h": "1d"}
HIGHER_EMA = 50
ATR_BARS = 14
PULLBACK_BARS = 5  # the dip to the fast EMA: the signal candle or the 5 before it
MIN_STOP_ATR, MAX_STOP_ATR = 0.5, 1.0  # the initial stop's distance from the entry
TRAIL_ATR = 3.0
BREAK_EVEN_PROFIT = 0.002  # the break-even stop sits this far above the entry: fees + slippage

PULLBACK_ENTRY = "pullback_entry"  # either direction
STOP_LOSS_EXIT = "stop_loss"
BREAK_EVEN_EXIT = "break_even"
TRAILING_STOP_EXIT = "trailing_stop"

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Indicators:
    """Per candle, oldest first."""

    fast: list[float]
    mid: list[float]
    slow: list[float]
    atr: list[float]
    higher_up: list[bool]


def ema(values: list[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def atr_series(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    """Average true range, smoothed over ATR_BARS candles (Wilder)."""
    out = [highs[0] - lows[0]]
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        out.append(out[-1] + (tr - out[-1]) / ATR_BARS)
    return out


def higher_uptrend(times: list[datetime], closes: list[float], timeframe: str) -> list[bool]:
    """Per candle: the last higher-timeframe candle closed by its close
    closes above its HIGHER_EMA, the EMA rising. A candle ending on a
    higher-timeframe boundary closes that candle with its close. True for a
    timeframe without a higher one."""
    higher = HIGHER_TIMEFRAME.get(timeframe)
    if higher is None:
        return [True] * len(closes)
    step = timedelta(minutes=INTERVAL_MINUTES[timeframe])
    higher_step = timedelta(minutes=INTERVAL_MINUTES[higher])
    k = 2 / (HIGHER_EMA + 1)
    out: list[bool] = []
    average: float | None = None
    up = False
    for t, close in zip(times, closes, strict=True):
        if (t + step - EPOCH) % higher_step == timedelta(0):
            previous = average
            average = close if previous is None else previous + k * (close - previous)
            up = previous is not None and close > average > previous
        out.append(up)
    return out


def indicators(
    times: list[datetime],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    timeframe: str,
) -> Indicators:
    return Indicators(
        ema(closes, FAST_EMA),
        ema(closes, MID_EMA),
        ema(closes, SLOW_EMA),
        atr_series(highs, lows, closes),
        higher_uptrend(times, closes, timeframe),
    )


@dataclass(frozen=True)
class Side:
    """One direction's view of the candles. The rules below are written for a
    long; a short is a long on the negated prices (highs and lows swapped), so
    `sign` x a real price is a price in this view and back."""

    direction: Direction
    sign: int
    highs: list[float]
    lows: list[float]
    closes: list[float]
    ind: Indicators


def side(
    direction: Direction,
    times: list[datetime],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    timeframe: str,
) -> Side:
    if direction == "short":
        highs, lows, closes = [-x for x in lows], [-x for x in highs], [-x for x in closes]
    return Side(
        direction,
        1 if direction == "long" else -1,
        highs,
        lows,
        closes,
        indicators(times, highs, lows, closes, timeframe),
    )


def entry_stop(
    highs: list[float], lows: list[float], closes: list[float], ind: Indicators, i: int
) -> float | None:
    """Candle `i` closing a pullback in an uptrend: the initial stop of a long
    at its close, else None. Uptrend: the close above the slow EMA, the mid
    EMA above the slow one, the higher timeframe's uptrend. Pullback: a low
    at or under the fast EMA in the last PULLBACK_BARS + 1 candles; candle
    `i` closes above the fast EMA and the previous candle's high. Stop:
    under the pullback's lowest low, kept MIN_STOP_ATR..MAX_STOP_ATR x ATR
    under the close."""
    if i < max(SLOW_EMA, PULLBACK_BARS):
        return None
    close = closes[i]
    if close <= ind.slow[i] or ind.mid[i] <= ind.slow[i] or not ind.higher_up[i]:
        return None
    if close <= ind.fast[i] or close <= highs[i - 1]:
        return None
    window = range(i - PULLBACK_BARS, i + 1)
    if not any(lows[j] <= ind.fast[j] for j in window):
        return None
    a = ind.atr[i]
    swing_low = min(lows[j] for j in window)
    return min(max(swing_low, close - MAX_STOP_ATR * a), close - MIN_STOP_ATR * a)


def exit_stop(
    entry: float, initial_stop: float, highest: float | None, atr: float
) -> tuple[float, str]:
    """An open long's stop and the exit reason it closes with. `highest`: the
    highest high of the candles closed since entry (None before the first);
    at entry + 1R (R: entry - initial stop) the stop moves to break-even,
    then trails TRAIL_ATR x `atr` under `highest` once that's higher."""
    stop, reason = initial_stop, STOP_LOSS_EXIT
    if highest is None:
        return stop, reason
    if highest >= 2 * entry - initial_stop:
        # abs: a short's entry is negated (Side).
        stop, reason = entry + BREAK_EVEN_PROFIT * abs(entry), BREAK_EVEN_EXIT
    trail = highest - TRAIL_ATR * atr
    if trail > stop:
        stop, reason = trail, TRAILING_STOP_EXIT
    return stop, reason


class BullRunStrategy:
    name = "bullrun"

    async def before_poll(self, papers: list[Paper], poll_started_at: datetime) -> None:
        return None

    async def decide(self, tick: Tick) -> Signal | None:
        paper, position = tick.paper, tick.position
        candles = await recent_candles(paper.asset, paper.timeframe, CANDLE_LOOKBACK)
        if len(candles) <= SLOW_EMA:
            return None
        times = [c.open_time for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        closes = [float(c.close) for c in candles]
        price = float(await live_trade_price(paper.asset) or tick.price)
        step = timedelta(minutes=INTERVAL_MINUTES[paper.timeframe])
        if position is not None:
            held: Direction = "long" if position.direction == "long" else "short"
            s = side(held, times, highs, lows, closes, paper.timeframe)
            entry = s.sign * float(position.entry_price)
            recorded = (await exit_levels([position.id])).get(position.id, (None, None))[0]
            initial = s.sign * float(recorded) if recorded else entry - MAX_STOP_ATR * s.ind.atr[-1]
            since = [
                h
                for t, h in zip(times, s.highs, strict=True)
                if t + step > position.opened_at  # closed after the entry
            ]
            stop, reason = exit_stop(entry, initial, max(since, default=None), s.ind.atr[-1])
            return Signal("exit", held, reason) if s.sign * price <= stop else None
        directions: tuple[Direction, ...] = ("long", "short")
        for direction in directions:
            if not direction_allowed(paper.direction, direction):
                continue
            s = side(direction, times, highs, lows, closes, paper.timeframe)
            initial_stop = entry_stop(s.highs, s.lows, s.closes, s.ind, len(candles) - 1)
            if initial_stop is None or s.sign * price <= initial_stop:
                continue
            last_entry = await last_entry_at(paper, direction=direction)
            if last_entry is not None and last_entry >= candles[-1].open_time + step:
                return None  # one entry per signal candle
            return Signal(
                "enter",
                direction,
                PULLBACK_ENTRY,
                stop_loss_price=Decimal(str(s.sign * initial_stop)),
            )
        return None


if __name__ == "__main__":
    run_service("bullrun-executor", lambda: run(BullRunStrategy()))
