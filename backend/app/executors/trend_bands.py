"""Port of BigBeluga's "Dynamic Trend Bands & Anchored VWAP Signals" with its
default settings - see docs/regime-strategy-engine.md#trend-bands. Pure,
indexed by candle; shared by the Regime executor, its backtest and the
chart.

The trend flips bullish when a close crosses above the upper band (a double
EMA of the closes + BAND_ATR x ATR), bearish when one crosses below the lower
band. In a bullish trend a pivot high (PIVOT_LENGTH candles each side) arms a
break-up signal: the first later close at or above the VWAP of the highs
anchored at the latest local high. Bearish: mirrored on the lows."""

from dataclasses import dataclass

from app.executors.liquidity_swings import _pivot_high
from app.executors.vwap_signals import ema

BASELINE_LENGTH = 50
ATR_LENGTH = 100
BAND_ATR = 3.0
PIVOT_LENGTH = 10
CALC_BARS = 5000  # the indicator's calc_bars_count: the trend state depends on the whole path
# The double EMA (seeded with the first close) and the ATR settle: no bands -
# so no trend or signals - before this many candles.
WARMUP_BARS = 300


@dataclass(frozen=True)
class Bands:
    """Per candle, oldest first. ATR is None during its own warm-up, the bands
    during WARMUP_BARS."""

    upper: list[float | None]
    lower: list[float | None]
    atr: list[float | None]
    state: list[int]  # 1 bullish, -1 bearish, 0 before the first cross
    break_up: list[bool]
    break_dn: list[bool]


def atr(highs: list[float], lows: list[float], closes: list[float], n: int) -> list[float | None]:
    """ta.atr: Wilder's average of the true range, seeded with the simple
    average of the first `n`."""
    out: list[float | None] = []
    trs: list[float] = []
    a: float | None = None
    for i in range(len(highs)):
        tr = highs[i] - lows[i]
        if i > 0:
            tr = max(tr, abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        if a is None:
            trs.append(tr)
            if len(trs) == n:
                a = sum(trs) / n
        else:
            a += (tr - a) / n
        out.append(a)
    return out


def _states(closes: list[float], upper: list[float | None], lower: list[float | None]) -> list[int]:
    out: list[int] = []
    state = 0
    for i, close in enumerate(closes):
        if i > 0:
            u0, u1, l0, l1 = upper[i], upper[i - 1], lower[i], lower[i - 1]
            if u0 is not None and u1 is not None and close > u0 and closes[i - 1] <= u1:
                state = 1
            if l0 is not None and l1 is not None and close < l0 and closes[i - 1] >= l1:
                state = -1
        out.append(state)
    return out


def _breaks_up(
    highs: list[float], closes: list[float], volumes: list[float], state: list[int], n: int
) -> list[bool]:
    """The bullish signals. The VWAP of the previous candle's high restarts on
    the candle after a local high (the highest of the last `n` candles); a
    pivot high confirmed in a bullish trend (bullish `n` candles earlier too)
    arms the signal, the first close at or above that VWAP fires it - not on
    a candle confirming another pivot high. A trend flip disarms it."""
    out = [False] * len(closes)
    armed = False
    pv = vol = 0.0
    for i in range(1, len(closes)):
        if i >= n - 1:
            top = max(highs[i - n + 1 : i + 1])
            if highs[i - 1] == top and highs[i] < top:
                pv = vol = 0.0
        pv += highs[i - 1] * volumes[i]
        vol += volumes[i]
        p = i - n
        pivot = p >= n and _pivot_high(highs, p, n)
        if state[i] == 1:
            if pivot and state[p] == 1:
                armed = True
            elif armed and not pivot and vol > 0 and closes[i] >= pv / vol:
                out[i], armed = True, False
        if state[i] != state[i - 1]:
            armed = False
    return out


def trend_bands(
    highs: list[float], lows: list[float], closes: list[float], volumes: list[float]
) -> Bands:
    a = atr(highs, lows, closes, ATR_LENGTH)
    center = ema(ema(closes, BASELINE_LENGTH), BASELINE_LENGTH)
    ready = [x if k >= WARMUP_BARS else None for k, x in enumerate(a)]
    upper = [None if x is None else c + BAND_ATR * x for c, x in zip(center, ready, strict=True)]
    lower = [None if x is None else c - BAND_ATR * x for c, x in zip(center, ready, strict=True)]
    state = _states(closes, upper, lower)
    # Bearish signals: the bullish rule on the negated prices.
    negated = [-s for s in state]
    return Bands(
        upper,
        lower,
        a,
        state,
        _breaks_up(highs, closes, volumes, state, PIVOT_LENGTH),
        _breaks_up([-x for x in lows], [-x for x in closes], volumes, negated, PIVOT_LENGTH),
    )
