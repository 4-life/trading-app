"""Port of the "Supertrend" indicator (KivancOzbilgic) with a source of choice -
see docs/swings.md#supertrend-on-the-trendlines. Pure, indexed by candle;
traded by the Supertrend executor (app/executors/supertrend.py) and its backtest.

A band ATR_MULT x ATR(ATR_PERIOD) under the source (up) and one over it (dn),
each only moving toward the price while the previous close stays on its
side. The trend turns down on a close under the previous up band, up on a
close over the previous dn band. Two instances run on the Trendlines with
Breaks lines (app/executors/trendlines.py): the upper one and the lower one
as the source."""

from dataclasses import dataclass

from app.executors.trend_bands import atr
from app.executors.trendlines import trendlines

ATR_PERIOD = 10
ATR_MULT = 3.0


@dataclass(frozen=True)
class Supertrend:
    """Per candle, oldest first. None (no trend, no signal) while the source
    or the ATR has no value - a run starts over on the next candle with both."""

    line: list[float | None]  # the up band in an uptrend, the dn band in a downtrend
    trend: list[int | None]  # 1 up, -1 down
    buy: list[bool]  # the trend turned up at this close
    sell: list[bool]  # the trend turned down at this close


def supertrend(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    src: list[float | None],
    period: int = ATR_PERIOD,
    mult: float = ATR_MULT,
) -> Supertrend:
    a = atr(highs, lows, closes, period)  # changeATR on: Wilder's
    n = len(closes)
    line: list[float | None] = [None] * n
    trends: list[int | None] = [None] * n
    buy = [False] * n
    sell = [False] * n
    up = dn = 0.0
    trend: int | None = None  # the previous candle's; None: a run starts here
    for i in range(n):
        s, v = src[i], a[i]
        if s is None or v is None:
            trend = None
            continue
        new_up, new_dn = s - mult * v, s + mult * v
        if trend is None:  # nz(up[1], up): the first candle of a run is its own previous
            up1, dn1, prev = new_up, new_dn, 1
        else:
            up1, dn1, prev = up, dn, trend
            if closes[i - 1] > up1:
                new_up = max(new_up, up1)
            if closes[i - 1] < dn1:
                new_dn = min(new_dn, dn1)
        up, dn = new_up, new_dn
        now = 1 if prev == -1 and closes[i] > dn1 else -1 if prev == 1 and closes[i] < up1 else prev
        if trend is not None:
            buy[i] = now == 1 and trend == -1
            sell[i] = now == -1 and trend == 1
        trend = now
        trends[i] = now
        line[i] = up if now == 1 else dn
    return Supertrend(line, trends, buy, sell)


def trendline_supertrends(
    highs: list[float], lows: list[float], closes: list[float]
) -> tuple[Supertrend, Supertrend]:
    """The Supertrend on the Trendlines with Breaks upper line, and on the lower one."""
    t = trendlines(highs, lows, closes)
    return (
        supertrend(highs, lows, closes, t.upper),
        supertrend(highs, lows, closes, t.lower),
    )
