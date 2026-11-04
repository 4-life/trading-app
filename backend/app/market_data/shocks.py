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
- Unusual move, any coin: its UNUSUAL_SPAN move is UNUSUAL x its own normal
  one or more (the standard deviation of those moves over the UNUSUAL_BASELINE
  before it) and UNUSUAL_MIN_MOVE at least, its last BURST_SPAN's volume
  BURST_VOLUME_SPIKE x its usual. BTC's is a market event if BREADTH of the
  other coins move UNUSUAL_BREADTH_MOVE the same way (skipped with fewer than
  MIN_COINS), otherwise on BTC's chart only. A coin's waits while a market
  event of its kind is under COOLDOWN old: a crash isn't an event per coin.
- A move normal for the coin isn't a coin event, whatever its volume: a coin
  panic / bullrun's move (the 4h one against BTC, or the unusual one) must be
  DAILY_RANGE_SHARE of the coin's usual day at least - the median high-to-low of
  its closes over the DAILY_RANGE_DAYS before (with DAILY_RANGE_MIN_DAYS known).
  Market events aren't filtered.

"Usual" volume: the median volume of the VOLUME_WINDOWS windows before. One
event of a kind per COOLDOWN - its first candle."""

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import cached_property
from itertools import accumulate
from math import sqrt
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
UNUSUAL_SPAN = timedelta(minutes=30)
UNUSUAL = 6.0  # x the coin's normal move
UNUSUAL_MIN_MOVE = 0.01  # a coin hardly moving (a closed stock market) has a tiny normal
UNUSUAL_BASELINE = timedelta(days=7)
UNUSUAL_BREADTH_MOVE = 0.01
BURST_SPAN = timedelta(minutes=15)
BURST_VOLUME_SPIKE = 3.0
DAILY_RANGE_SHARE = 0.75
DAILY_RANGE_DAYS = 7
DAILY_RANGE_MIN_DAYS = 3

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
    volume = (VOLUME_WINDOWS + 2) * _candles(FOUR_HOURS, step)
    unusual = _candles(UNUSUAL_BASELINE, step) + 2 * _candles(UNUSUAL_SPAN, step)
    return max(volume, unusual, _candles(timedelta(days=DAILY_RANGE_DAYS + 1), step))


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

    @cached_property
    def _moves(self) -> tuple[list[int], list[float], list[float]]:
        """Running count, sum and sum of squares of the UNUSUAL_SPAN moves."""
        n = _candles(UNUSUAL_SPAN, self.step)
        count, total, squares = [0], [0.0], [0.0]
        for t in self.times:
            m = self.change(t, n)
            count.append(count[-1] + (m is not None))
            total.append(total[-1] + (m or 0.0))
            squares.append(squares[-1] + (m or 0.0) ** 2)
        return count, total, squares

    def unusual(self, t: datetime) -> tuple[float, float] | None:
        """The UNUSUAL_SPAN move to `t` and how many times the normal one it is
        - the standard deviation of those moves over the UNUSUAL_BASELINE
        before it (half of it known at least, else None)."""
        i = self.at.get(t)
        n = _candles(UNUSUAL_SPAN, self.step)
        length = _candles(UNUSUAL_BASELINE, self.step)
        move = self.change(t, n)
        if i is None or move is None:
            return None
        end = max(0, i - n + 1)
        begin = max(0, end - length)
        count, total, squares = self._moves
        known = count[end] - count[begin]
        if known < length // 2:
            return None
        mean = (total[end] - total[begin]) / known
        variance = (squares[end] - squares[begin]) / known - mean * mean
        return None if variance <= 0 else (move, abs(move) / sqrt(variance))

    @cached_property
    def _day_ranges(self) -> dict[date, float]:
        """Each day's high-to-low of the closes, a share of its low."""
        days: dict[date, list[float]] = {}
        for t, close in zip(self.times, self.closes, strict=True):
            if close > 0:
                days.setdefault(t.date(), []).append(close)
        return {day: max(closes) / min(closes) - 1 for day, closes in days.items()}

    def usual_day(self, t: datetime) -> float | None:
        """The median of the DAILY_RANGE_DAYS' ranges before `t`'s day; None:
        fewer than DAILY_RANGE_MIN_DAYS known."""
        ranges = self._day_ranges
        days = (t.date() - timedelta(days=k) for k in range(1, DAILY_RANGE_DAYS + 1))
        known = [ranges[day] for day in days if day in ranges]
        return median(known) if len(known) >= DAILY_RANGE_MIN_DAYS else None

    def beats_usual_day(self, t: datetime, move: float) -> bool:
        """`move` isn't normal for the coin (unknown: it counts)."""
        usual = self.usual_day(t)
        return usual is None or abs(move) >= DAILY_RANGE_SHARE * usual

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
    span, burst = _candles(UNUSUAL_SPAN, step), _candles(BURST_SPAN, step)
    labels = {HOUR: "1h", FOUR_HOURS: "4h"}
    last: dict[tuple[str, str], datetime] = {}
    out: list[Shock] = []

    def emit(t: datetime, kind: Kind, scope: Scope, text: str) -> None:
        at = last.get((kind, scope))
        if at is None or t - at >= COOLDOWN:
            out.append(Shock(t, t + step, kind, scope, text))
        last[(kind, scope)] = t

    def unusual_move(track: _Track, t: datetime) -> tuple[float, float, float] | None:
        """`track`'s move to `t` if unusual: (the move, x its normal, volume spike)."""
        found = track.unusual(t)
        if found is None or found[1] < UNUSUAL or abs(found[0]) < UNUSUAL_MIN_MOVE:
            return None
        burst_spike = track.spike(t, burst)
        if burst_spike is None or burst_spike < BURST_VOLUME_SPIKE:
            return None
        return found[0], found[1], burst_spike

    def unusual_text(coin_name: str, found: tuple[float, float, float]) -> str:
        return (
            f"{coin_name} {_pct(found[0])} in 30m · {found[1]:.1f}× its normal"
            f" · volume {found[2]:.1f}×"
        )

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
        btc_unusual = unusual_move(btc, t)
        if btc_unusual is not None:
            sign = 1 if btc_unusual[0] > 0 else -1
            moves = [m for s in others if (m := s.change(t, span)) is not None]
            same = sum(1 for m in moves if sign * m >= UNUSUAL_BREADTH_MOVE)
            broad = len(moves) >= MIN_COINS and same / len(moves) >= BREADTH
            text = unusual_text(REGIME_ASSET, btc_unusual)
            kind: Kind = "bullrun" if sign > 0 else "panic"
            if broad or len(moves) < MIN_COINS:
                way = "up" if sign > 0 else "down"
                breadth = f"{same} of {len(moves)} coins {way}" if broad else "no breadth"
                emit(t, kind, "market", f"{text} · {breadth}")
            elif asset == REGIME_ASSET and btc.beats_usual_day(t, btc_unusual[0]):
                emit(t, kind, "coin", text)
        if coin is None:
            continue
        coin_unusual = unusual_move(coin, t)
        if coin_unusual is not None:
            kind = "bullrun" if coin_unusual[0] > 0 else "panic"
            market_at = last.get((kind, "market"))
            if (market_at is None or t - market_at >= COOLDOWN) and coin.beats_usual_day(
                t, coin_unusual[0]
            ):
                emit(t, kind, "coin", unusual_text(asset, coin_unusual))
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
        if (
            abs(relative) >= RELATIVE
            and fast
            and own_spike >= COIN_VOLUME_SPIKE
            and coin.beats_usual_day(t, relative)
        ):
            fast_move = _pct(own_hour - base_hour)
            text = (
                f"{asset} {_pct(own)} vs BTC {_pct(base)} in 4h ({fast_move} in 1h)"
                f" · volume {own_spike:.1f}×"
            )
            emit(t, "bullrun" if relative > 0 else "panic", "coin", text)
    return out
