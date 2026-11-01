"""ATR stop-loss - a port of the "Average True Range Stop Loss Finder"
TradingView indicator with SMA smoothing, length LENGTH and multiplier
MULTIPLIER (docs/strategy-executor.md#atr-stop-loss). For any strategy;
nothing uses it yet.

A long's stop sits ATR x MULTIPLIER under the candle's low, a short's the
same above its high - ATR: the simple average of the last LENGTH true
ranges."""

from decimal import Decimal

from app.executors.base import recent_candles
from app.feature_engine.indicators import atr
from app.order_queue import Direction

LENGTH = 20
MULTIPLIER = 1.2


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
    a = atr(highs, lows, closes, length)
    if a is None:
        return None
    return lows[-1] - a * multiplier if direction == "long" else highs[-1] + a * multiplier


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
