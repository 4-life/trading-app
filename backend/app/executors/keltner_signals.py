"""Port of the "Keltner Channel signals" indicator's Buy / Sell with its
defaults - see docs/keltner-strategy-engine.md#signals. Pure, indexed by
candle; traded by the Keltner executor (app/executors/keltner.py) and its
backtest.

A band DEVIATION x stdev(close, LENGTH) around the channel's base, an
EMA(close, LENGTH); %B the close's place in it (0 the lower edge, 1 the
upper). %B climbing back over 0 marks a support at the previous candle's
low, falling back under 1 a resistance at its high. Buy: the support level
moves, Sell: the resistance level moves. The channel's ATR bands and the
WaveTrend only draw in the original - they aren't ported."""

from dataclasses import dataclass
from math import sqrt

from app.executors.vwap_signals import ema

LENGTH = 34
DEVIATION = 2.0
OVERBOUGHT = 1.0
OVERSOLD = 0.0


@dataclass(frozen=True)
class KeltnerSignals:
    """Per candle, oldest first."""

    buy: list[bool]  # the support moved at this close
    sell: list[bool]  # the resistance moved at this close


def percent_b(
    closes: list[float], length: int = LENGTH, mult: float = DEVIATION
) -> list[float | None]:
    """The close's place in the band, None before `length` closes or on a
    flat band."""
    base = ema(closes, length) if closes else []
    out: list[float | None] = []
    for i, close in enumerate(closes):
        if i + 1 < length:
            out.append(None)
            continue
        window = closes[i + 1 - length : i + 1]
        mean = sum(window) / length
        dev = mult * sqrt(sum((x - mean) ** 2 for x in window) / length)  # Pine's stdev
        out.append(None if dev == 0 else (close - base[i] + dev) / (2 * dev))
    return out


def _moved(level: list[float]) -> list[bool]:
    """crossover(level, level[1]) or crossunder(level, level[1])."""
    return [
        i >= 2
        and (
            (level[i] > level[i - 1] and level[i - 1] <= level[i - 2])
            or (level[i] < level[i - 1] and level[i - 1] >= level[i - 2])
        )
        for i in range(len(level))
    ]


def keltner_signals(highs: list[float], lows: list[float], closes: list[float]) -> KeltnerSignals:
    bbr = percent_b(closes)
    support = [0.0] * len(closes)
    resistance = [0.0] * len(closes)
    for i in range(1, len(closes)):
        support[i], resistance[i] = support[i - 1], resistance[i - 1]
        prev, now = bbr[i - 1], bbr[i]
        if prev is None or now is None:
            continue
        if prev < OVERSOLD < now:
            support[i] = lows[i - 1]
        if prev > OVERBOUGHT > now:
            resistance[i] = highs[i - 1]
    return KeltnerSignals(_moved(support), _moved(resistance))
