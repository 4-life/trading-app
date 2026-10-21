"""Port of LuxAlgo's "Trendlines with Breaks" - see docs/swings.md#trendlines-with-breaks.
Pure, indexed by candle; feeds the Supertrend (app/executors/supertrend_signals.py),
not drawn on the chart yet.

A pivot high (LENGTH candles each side, known LENGTH candles later) starts a
falling upper trendline at its price, sloped by the volatility at its
confirmation; a pivot low a rising lower one. A close above the upper line
projected to the current candle is a break-up, below the lower one a
break-down - once per pivot. Values are the real-time ones (the indicator's
backpaint off): each line as projected to the candle it's read at."""

import math
from dataclasses import dataclass
from typing import Literal

from app.executors.liquidity_swings import _pivot_high, _pivot_low
from app.executors.trend_bands import atr

LENGTH = 14  # swing detection lookback
MULT = 0.5  # slope multiplier (the indicator's default: 1)
SlopeMethod = Literal["atr", "stdev", "linreg"]


@dataclass(frozen=True)
class Trendlines:
    """Per candle, oldest first. A line is None until its first pivot (and
    while its slope is still warming up)."""

    upper: list[float | None]  # the down-trendline at this candle
    lower: list[float | None]  # the up-trendline at this candle
    break_up: list[bool]  # the close broke the down-trendline upward
    break_dn: list[bool]  # the close broke the up-trendline downward


def _stdev(xs: list[float]) -> float:
    """ta.stdev: the population standard deviation."""
    mean = sum(xs) / len(xs)
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs))


def slopes(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    length: int = LENGTH,
    mult: float = MULT,
    method: SlopeMethod = "atr",
) -> list[float | None]:
    """The slope per candle: ATR, the closes' standard deviation, or the
    linear regression's slope (halved), each over `length` / `length` x `mult`
    (the linreg one already per candle). None during the warm-up."""
    if method == "atr":
        return [None if a is None else a / length * mult for a in atr(highs, lows, closes, length)]
    out: list[float | None] = []
    for i in range(len(closes)):
        if i + 1 < length:
            out.append(None)
            continue
        window = closes[i + 1 - length : i + 1]
        if method == "stdev":
            out.append(_stdev(window) / length * mult)
            continue
        xs = range(i + 1 - length, i + 1)  # bar_index
        mean_x = sum(xs) / length
        mean_y = sum(window) / length
        covariance = sum(x * y for x, y in zip(xs, window, strict=True)) / length - mean_x * mean_y
        variance = sum((x - mean_x) ** 2 for x in xs) / length  # ta.variance: population
        out.append(abs(covariance) / variance / 2 * mult)
    return out


def trendlines(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    length: int = LENGTH,
    mult: float = MULT,
    method: SlopeMethod = "atr",
) -> Trendlines:
    slope = slopes(highs, lows, closes, length, mult, method)
    n = len(closes)
    upper_out: list[float | None] = []
    lower_out: list[float | None] = []
    break_up = [False] * n
    break_dn = [False] * n
    # Pine's `var`s: the lines from their pivot's price, carried down / up by
    # their slope - none before the first pivot (Pine's 0 there breaks nothing).
    upper: float | None = None
    lower: float | None = None
    slope_ph: float | None = None
    slope_pl: float | None = None
    upos = dnos = 0
    for i in range(n):
        p = i - length  # the pivot confirmed at this candle
        ph = p >= length and _pivot_high(highs, p, length)
        pl = p >= length and _pivot_low(lows, p, length)
        if ph:
            slope_ph, upper = slope[i], highs[p]
        elif upper is not None and slope_ph is not None:
            upper -= slope_ph
        else:
            upper = None
        if pl:
            slope_pl, lower = slope[i], lows[p]
        elif lower is not None and slope_pl is not None:
            lower += slope_pl
        else:
            lower = None
        # The lines projected from their pivot to this candle.
        up_now = None if upper is None or slope_ph is None else upper - slope_ph * length
        dn_now = None if lower is None or slope_pl is None else lower + slope_pl * length
        prev_up, prev_dn = upos, dnos
        if ph:
            upos = 0
        elif up_now is not None and closes[i] > up_now:
            upos = 1
        if pl:
            dnos = 0
        elif dn_now is not None and closes[i] < dn_now:
            dnos = 1
        break_up[i] = upos > prev_up
        break_dn[i] = dnos > prev_dn
        upper_out.append(up_now)
        lower_out.append(dn_now)
    return Trendlines(upper_out, lower_out, break_up, break_dn)
