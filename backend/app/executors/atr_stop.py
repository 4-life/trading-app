"""ATR stop-loss - a port of the "Average True Range Stop Loss Finder"
TradingView indicator with SMA smoothing, length LENGTH and multiplier
MULTIPLIER (docs/strategy-executor.md#atr-stop-loss). For any strategy;
Keltner averaging stops at its entry candle's line
(app/executors/keltner_averaging.py).

A long's stop sits ATR x MULTIPLIER under the candle's low, a short's the
same above its high - ATR: the simple average of the last LENGTH true
ranges."""

from decimal import Decimal

from app.executors.base import recent_candles
from app.order_queue import Direction

LENGTH = 20
MULTIPLIER = 1.2
ATR_STOP_EXIT = "atr_stop"  # exit reason: the price reached the ATR stop


def atr_series(
    highs: list[float], lows: list[float], closes: list[float], length: int = LENGTH
) -> list[float | None]:
    """Per candle, oldest first: the simple average of the last `length` true
    ranges (as feature_engine's atr()); None before `length` + 1 candles."""
    trs = [0.0] + [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, len(highs))
    ]
    out: list[float | None] = []
    total = 0.0
    for i, tr in enumerate(trs):
        total += tr
        if i > length:
            total -= trs[i - length]
        out.append(total / length if i >= length else None)
    return out


def atr_lines(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    length: int = LENGTH,
    multiplier: float = MULTIPLIER,
) -> tuple[list[float | None], list[float | None]]:
    """Per candle, oldest first: the long stop (its low - ATR x `multiplier`)
    and the short stop (its high + ATR x `multiplier`); None before `length`
    + 1 candles."""
    atr = atr_series(highs, lows, closes, length)
    long = [None if a is None else lo - a * multiplier for a, lo in zip(atr, lows, strict=True)]
    short = [None if a is None else hi + a * multiplier for a, hi in zip(atr, highs, strict=True)]
    return long, short


def atr_stop(
    direction: Direction,
    highs: list[float],
    lows: list[float],
    closes: list[float],
    length: int = LENGTH,
    multiplier: float = MULTIPLIER,
) -> float | None:
    """The stop-loss on the last candle (oldest first); None before
    `length` + 1 candles."""
    if not highs:
        return None
    long, short = atr_lines(highs, lows, closes, length, multiplier)
    return long[-1] if direction == "long" else short[-1]


async def stop_loss(asset: str, timeframe: str, direction: Direction) -> Decimal | None:
    """The stop-loss for a `direction` position on `asset` now: on its last
    closed candle at `timeframe`."""
    candles = await recent_candles(asset, timeframe, LENGTH + 1)
    stop = atr_stop(
        direction,
        [float(c.high) for c in candles],
        [float(c.low) for c in candles],
        [float(c.close) for c in candles],
    )
    return None if stop is None else Decimal(str(stop))
