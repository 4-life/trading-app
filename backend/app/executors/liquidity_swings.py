"""Port of LuxAlgo "Liquidity Swings" (Full Range zones, filtered by Count) -
see docs/swings.md#liquidity-swings. Pure, indexed by candle.

A swing low (green) / high (red) is a pivot with LENGTH candles on each side.
Its zone is the pivot candle's full range (low..high). Each later candle that
trades into the zone adds 1 to its count (Pine looks LENGTH candles back, so
the count trails by LENGTH candles); the zone is "confirmed" - the indicator
shows its label - on the candle where the count first exceeds MIN_COUNT.
A close beyond the zone (below a swing low, above a swing high) breaks it."""

from dataclasses import dataclass
from typing import Literal

LENGTH = 14
MIN_COUNT = 1


def _pivot_high(highs: list[float], p: int, n: int) -> bool:
    """TradingView's pivothigh: above every bar on the left, not exceeded on the right."""
    return all(highs[p] > highs[j] for j in range(p - n, p)) and all(
        highs[p] >= highs[j] for j in range(p + 1, p + n + 1)
    )


def _pivot_low(lows: list[float], p: int, n: int) -> bool:
    return all(lows[p] < lows[j] for j in range(p - n, p)) and all(
        lows[p] <= lows[j] for j in range(p + 1, p + n + 1)
    )


@dataclass
class Zone:
    kind: Literal["low", "high"]  # low = green swing, high = red swing
    pivot_index: int
    top: float
    btm: float
    count: int = 0
    confirm_index: int | None = None  # the candle whose close showed the label
    broken_index: int | None = None  # the first close beyond the zone

    @property
    def broken_at_confirm(self) -> bool:
        return self.broken_index is not None and (
            self.confirm_index is None or self.broken_index <= self.confirm_index
        )


def liquidity_zones(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    length: int = LENGTH,
    min_count: int = MIN_COUNT,
) -> list[Zone]:
    """Every swing zone, oldest first. A zone stops counting when the next
    swing of the same kind appears (the indicator moves on to it)."""
    zones: list[Zone] = []
    current: dict[str, Zone] = {}
    for n in range(2 * length, len(closes)):
        p = n - length
        new = {
            "low": _pivot_low(lows, p, length),
            "high": _pivot_high(highs, p, length),
        }
        kinds: tuple[Literal["low", "high"], ...] = ("low", "high")
        for kind in kinds:
            if new[kind]:
                fresh = Zone(kind, p, highs[p], lows[p])  # Full Range
                zones.append(fresh)
                current[kind] = fresh
                continue
            zone = current.get(kind)
            if zone is None:
                continue
            if lows[p] < zone.top and highs[p] > zone.btm:
                zone.count += 1
            beyond = closes[n] < zone.btm if kind == "low" else closes[n] > zone.top
            if beyond and zone.broken_index is None:
                zone.broken_index = n
            if zone.confirm_index is None and zone.count > min_count:
                zone.confirm_index = n
    return zones
