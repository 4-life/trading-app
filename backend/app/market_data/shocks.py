"""Market-shock detector - see docs/market-shocks.md. Pure, from closed
candles at one timeframe (1m, the chart falling back to its own); the
strategy chart draws its events (app/api/chart.py), the risk engine holds
back the entries against one (app/market_data/shock_state.py).

- Market panic / bullrun: BTC moves fast in one of the WINDOWS (an hour or
  four: its speed or more), BREADTH of the other coins move the window's
  breadth move or more the same way (skipped with fewer than MIN_COINS
  others with candles), on BTC volume the window's spike x its usual.
- Coin panic / bullrun (the chart's coin, not BTC): its 4h return beats
  BTC's by RELATIVE or more (bullrun; trails it: panic), COIN_SPEED or more
  of it within the last hour (a jump, not a slow climb), on its own volume
  COIN_VOLUME_SPIKE x its usual.

"Usual" volume: the median volume of the VOLUME_WINDOWS windows before. One
event of a kind per COOLDOWN - its first candle."""

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import accumulate
from statistics import median
from typing import Literal

from app.papers.models import REGIME_ASSET

BREADTH = 0.7
MIN_COINS = 3  # breadth needs this many other coins with candles
RELATIVE = 0.05
# A coin event's 1h return against BTC's, the same way, at least: a steady
# 4h climb (ZEC +6.7% vs BTC +0.9% on 2026-11-03) isn't a shock.
COIN_SPEED = 0.03
COIN_VOLUME_SPIKE = 3.0
VOLUME_WINDOWS = 20
COOLDOWN = timedelta(hours=6)

HOUR = timedelta(hours=1)
FOUR_HOURS = timedelta(hours=4)


@dataclass(frozen=True)
class Window:
    span: timedelta
    speed: float  # BTC's move within it at least
    breadth_move: float  # a coin's move within it to count as the same way
    volume_spike: float  # BTC's volume in it against its usual at least


# A crash within an hour, or a slide over four (the 2026-10-29 Binance hack:
# -2.5% in 1h, -4.2% in 4h - the next biggest in October -1.6% / -2.0%). A
# 15-minute window flagged it 2 minutes sooner but with many false alarms.
WINDOWS = (
    Window(HOUR, 0.02, 0.015, 4.0),
    Window(FOUR_HOURS, 0.035, 0.03, 2.5),
)

# A candle: (close, volume), by open time.
Series = dict[datetime, tuple[float, float]]
Kind = Literal["panic", "bullrun"]
Scope = Literal["market", "coin"]


@dataclass(frozen=True)
class Shock:
    time: datetime  # the candle's open time
    detected_at: datetime  # its close - when the detector knew
    kind: Kind
    scope: Scope
    text: str


def _candles(span: timedelta, step: timedelta) -> int:
    return max(1, span // step)


def lookback(step: timedelta) -> int:
    """Candles needed before the first one checked."""
    return (VOLUME_WINDOWS + 2) * _candles(FOUR_HOURS, step)


class _Track:
    """One coin's candles, indexed - its returns and volume spikes in O(1)."""

    def __init__(self, series: Series, step: timedelta) -> None:
        self.times = sorted(series)
        self.at = {t: i for i, t in enumerate(self.times)}
        self.closes = [series[t][0] for t in self.times]
        self.volume = [0.0, *accumulate(series[t][1] for t in self.times)]
        self.step = step

    def change(self, t: datetime, n: int) -> float | None:
        i, j = self.at.get(t), self.at.get(t - n * self.step)
        if i is None or j is None or self.closes[j] == 0:
            return None
        return self.closes[i] / self.closes[j] - 1

    def spike(self, t: datetime, n: int) -> float | None:
        """The last `n` candles' volume against the median of the
        VOLUME_WINDOWS windows of `n` before them."""
        i = self.at.get(t)
        if i is None or i + 1 < n:
            return None
        recent = self.volume[i + 1] - self.volume[i + 1 - n]
        before = [
            self.volume[end] - self.volume[end - n]
            for k in range(1, VOLUME_WINDOWS + 1)
            if (end := i + 1 - k * n) >= n
        ]
        if len(before) < VOLUME_WINDOWS // 2:
            return None
        usual = median(before)
        return None if usual == 0 else recent / usual

    def since(self, start: datetime) -> list[datetime]:
        return self.times[bisect_left(self.times, start) :]


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def market_shocks(
    series: dict[str, Series], asset: str, step: timedelta, start: datetime
) -> list[Shock]:
    """The events on `asset`'s chart from `start`: the market's, and the
    coin's own (not on BTC's), oldest first. `series`: every coin's candles
    at the timeframe `step`, BTC's included."""
    if not series.get(REGIME_ASSET):
        return []
    btc = _Track(series[REGIME_ASSET], step)
    others = [_Track(s, step) for a, s in series.items() if a != REGIME_ASSET]
    coin = _Track(series[asset], step) if asset != REGIME_ASSET and series.get(asset) else None
    hour, four = _candles(HOUR, step), _candles(FOUR_HOURS, step)
    labels = {HOUR: "1h", FOUR_HOURS: "4h"}
    last: dict[tuple[str, str], datetime] = {}
    out: list[Shock] = []

    def emit(t: datetime, kind: Kind, scope: Scope, text: str) -> None:
        at = last.get((kind, scope))
        if at is None or t - at >= COOLDOWN:
            out.append(Shock(t, t + step, kind, scope, text))
        last[(kind, scope)] = t

    for t in btc.since(start):
        for w in WINDOWS:
            n = _candles(w.span, step)
            move = btc.change(t, n)
            spike = btc.spike(t, n)
            if move is None or spike is None or abs(move) < w.speed or spike < w.volume_spike:
                continue
            sign = 1 if move > 0 else -1
            moves = [m for s in others if (m := s.change(t, n)) is not None]
            same = sum(1 for m in moves if sign * m >= w.breadth_move)
            if len(moves) >= MIN_COINS and same / len(moves) < BREADTH:
                continue
            way = "up" if sign > 0 else "down"
            breadth = "no breadth"
            if len(moves) >= MIN_COINS:
                breadth = f"{same} of {len(moves)} coins {way}"
            text = f"BTC {_pct(move)} in {labels[w.span]} · {breadth} · volume {spike:.1f}×"
            emit(t, "bullrun" if sign > 0 else "panic", "market", text)
            break
        if coin is None:
            continue
        own, base = coin.change(t, four), btc.change(t, four)
        own_hour, base_hour = coin.change(t, hour), btc.change(t, hour)
        own_spike = coin.spike(t, hour)
        if own is None or base is None or own_hour is None or base_hour is None:
            continue
        if own_spike is None:
            continue
        relative = own - base
        sign = 1 if relative > 0 else -1
        fast = sign * (own_hour - base_hour) >= COIN_SPEED
        if abs(relative) >= RELATIVE and fast and own_spike >= COIN_VOLUME_SPIKE:
            fast_move = _pct(own_hour - base_hour)
            text = (
                f"{asset} {_pct(own)} vs BTC {_pct(base)} in 4h ({fast_move} in 1h)"
                f" · volume {own_spike:.1f}×"
            )
            emit(t, "bullrun" if relative > 0 else "panic", "coin", text)
    return out
