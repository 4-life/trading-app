"""Swing levels - the "Higher High Lower Low" Pine script's pivots and HH /
LL / HL / LH labels (docs/swings.md#swing-levels). Pure,
indexed by candle; used by the strategies, the shared executor loop
and the chart."""

from dataclasses import dataclass
from typing import Literal

Kind = Literal["HH", "LL", "HL", "LH"]

LEFT_BARS = 4
RIGHT_BARS = 4


@dataclass(frozen=True)
class Swing:
    kind: Kind
    price: float
    pivot_index: int  # the candle that made the high / low
    confirm_index: int  # RIGHT_BARS candles later - when it became known


def _pivot_high(highs: list[float], p: int, lb: int, rb: int) -> bool:
    """TradingView's pivothigh: above every bar on the left, not exceeded on the right."""
    return all(highs[p] > highs[j] for j in range(p - lb, p)) and all(
        highs[p] >= highs[j] for j in range(p + 1, p + rb + 1)
    )


def _pivot_low(lows: list[float], p: int, lb: int, rb: int) -> bool:
    return all(lows[p] < lows[j] for j in range(p - lb, p)) and all(
        lows[p] <= lows[j] for j in range(p + 1, p + rb + 1)
    )


def find_swings(
    highs: list[float], lows: list[float], lb: int = LEFT_BARS, rb: int = RIGHT_BARS
) -> list[Swing]:
    """Port of the "Higher High Lower Low" Pine script: pivots, the zigzag
    clean-up (drop a weaker repeated high / low and a low above the previous
    high or a high below the previous low), then each remaining pivot is
    labeled against the previous four (b, c, d, e). Indexed by candle, both
    series by the bar where the pivot is confirmed."""
    n = len(highs)
    hl: list[int | None] = [None] * n  # 1 = pivot high, -1 = pivot low
    zz: list[float | None] = [None] * n  # its price
    swings: list[Swing] = []
    # The latest non-empty hl / zz before bar i (Pine's valuewhen(x, x, 1)).
    prev_hl: int | None = None
    prev_zz: float | None = None
    for i in range(lb + rb, n):
        p = i - rb
        ph = highs[p] if _pivot_high(highs, p, lb, rb) else None
        pl = lows[p] if _pivot_low(lows, p, lb, rb) else None
        h = 1 if ph is not None else -1 if pl is not None else None
        z = ph if ph is not None else pl
        if prev_zz is not None:
            if pl is not None and h == -1 and prev_hl == -1 and pl > prev_zz:
                z = None
            if ph is not None and h == 1 and prev_hl == 1 and ph < prev_zz:
                z = None
            if z is not None and h == -1 and prev_hl == 1 and z > prev_zz:
                h = None
            if z is not None and h == 1 and prev_hl == -1 and z < prev_zz:
                h = None
        if h is None:
            z = None
        hl[i], zz[i] = h, z
        if h is not None:
            prev_hl = h
        if z is not None:
            prev_zz = z
        if h is None or z is None:
            continue

        # b, c, d, e: the previous opposite / same / opposite / same pivots.
        found: list[float] = []
        want = -h
        for j in range(i - 1, -1, -1):
            price = zz[j]
            if hl[j] == want and price is not None:
                found.append(price)
                want = -want
                if len(found) == 4:
                    break
        if len(found) < 4:
            continue
        a = z
        b, c, d, e = found
        if a > b and a > c and c > b and c > d:
            swings.append(Swing("HH", a, p, i))
        if a < b and a < c and c < b and c < d:
            swings.append(Swing("LL", a, p, i))
        if (a >= c and b > c and b > d and d > c and d > e) or (a < b and a > c and b < d):
            swings.append(Swing("HL", a, p, i))
        if (a <= c and b < c and b < d and d < c and d < e) or (a > b and a < c and b > d):
            swings.append(Swing("LH", a, p, i))
    return swings
