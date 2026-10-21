"""Trend strategy executor: catches big moves on a breakout and rides them
with a volatility trailing stop, under a hard 1% stop-loss checked on 1m
candles - see docs/trend-strategy-engine.md.
Run: python -m app.executors.trend"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.executors.base import Tick, latest_price, recent_candles, run
from app.feature_engine.engine import INTERVAL_MINUTES
from app.market_data.collector import PRICE_INTERVAL
from app.market_data.models import Candle
from app.notifications.error_reporting import run_service
from app.order_queue import Direction, Signal
from app.papers.models import Paper

# Standard settings, deliberately not tuned (docs: "Why these settings").
BREAKOUT_DAYS = 20
ATR_BARS = 14
TRAIL_ATR = 3.0
BEAR_SMA_DAYS = 200  # shorts only while BTC is below its 200-day average
REGIME_ASSET = "BTC"
STOP_LOSS_PCT = Decimal("0.01")  # from the entry, whatever the paper's timeframe
# Breakout confirmation (docs: "Breakout confirmation").
VOLUME_BARS = 20
VOLUME_MULTIPLE = 2.0  # the breakout candle's volume vs the previous VOLUME_BARS' average
STRONG_CLOSE = 0.75  # the close in the top (long) / bottom (short) quarter of the range

BREAKOUT_LONG = "breakout_high"
BREAKOUT_SHORT = "breakout_low"
TRAILING_STOP = "trailing_stop"
STOP_LOSS = "stop_loss_1pct"


@dataclass(frozen=True)
class Bar:
    open_time: datetime
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Held:
    direction: Direction
    opened_at: datetime


def bars_for_days(days: int, timeframe: str) -> int:
    return days * 24 * 60 // INTERVAL_MINUTES[timeframe]


def atr(bars: list[Bar], n: int = ATR_BARS) -> float:
    """Average true range, smoothed over `n` bars (Wilder)."""
    a = bars[0].high - bars[0].low
    for prev, bar in zip(bars, bars[1:], strict=False):
        tr = max(bar.high - bar.low, abs(bar.high - prev.close), abs(bar.low - prev.close))
        a += (tr - a) / n
    return a


def bear_market(closes: list[float], window: int) -> bool | None:
    """Last close below the `window`-bar average; None without enough history."""
    if len(closes) < window:
        return None
    return closes[-1] < sum(closes[-window:]) / window


def stop_loss_hit(direction: Direction, entry_price: Decimal, price: Decimal) -> bool:
    """`price`: the latest closed 1m candle's close."""
    if direction == "long":
        return price <= entry_price * (1 - STOP_LOSS_PCT)
    return price >= entry_price * (1 + STOP_LOSS_PCT)


def confirmed(bars: list[Bar], direction: Direction) -> bool:
    """The last candle's volume is at least VOLUME_MULTIPLE x the previous
    VOLUME_BARS' average, and it closes in the top (long) / bottom (short)
    quarter of its range - no big wick against the breakout."""
    last, previous = bars[-1], bars[-VOLUME_BARS - 1 : -1]
    if len(previous) < VOLUME_BARS:
        return False
    if last.volume < VOLUME_MULTIPLE * sum(b.volume for b in previous) / VOLUME_BARS:
        return False
    span = last.high - last.low
    if span <= 0:
        return False
    position = (last.close - last.low) / span
    return position >= STRONG_CLOSE if direction == "long" else position <= 1 - STRONG_CLOSE


def decide_signal(
    bars: list[Bar], breakout_bars: int, position: Held | None, bear: bool | None
) -> Signal | None:
    """`bars`: closed candles, oldest first. Flat: a close above the high of
    the previous `breakout_bars` candles opens a long; below their low opens
    a short - only in a bear market (`bear` is True); either only when
    `confirmed` (volume, strong close). Open: closes when a candle closes
    TRAIL_ATR x ATR beyond the best price since entry."""
    if len(bars) <= breakout_bars:
        return None
    last, a = bars[-1], atr(bars)
    if position is not None:
        since = [b for b in bars if b.open_time >= position.opened_at]
        if not since:
            return None
        if position.direction == "long":
            stop = max(b.high for b in since) - TRAIL_ATR * a
            hit = last.close < stop
        else:
            stop = min(b.low for b in since) + TRAIL_ATR * a
            hit = last.close > stop
        return Signal("exit", position.direction, TRAILING_STOP) if hit else None
    window = bars[-breakout_bars - 1 : -1]
    # Recorded on the entry: the nearer of the 1% stop and the initial
    # trailing stop (which then moves with the price).
    close = Decimal(str(last.close))
    if last.close > max(b.high for b in window) and confirmed(bars, "long"):
        sl = max(close * (1 - STOP_LOSS_PCT), Decimal(str(last.close - TRAIL_ATR * a)))
        return Signal("enter", "long", BREAKOUT_LONG, stop_loss_price=sl)
    if bear and last.close < min(b.low for b in window) and confirmed(bars, "short"):
        sl = min(close * (1 + STOP_LOSS_PCT), Decimal(str(last.close + TRAIL_ATR * a)))
        return Signal("enter", "short", BREAKOUT_SHORT, stop_loss_price=sl)
    return None


def _bars(candles: list[Candle]) -> list[Bar]:
    return [
        Bar(c.open_time, float(c.high), float(c.low), float(c.close), float(c.volume))
        for c in candles
    ]


class TrendStrategy:
    name = "trend"

    def __init__(self) -> None:
        # timeframe -> (latest closed BTC candle, bear?) - the 200-day window is
        # re-read only when a new BTC candle closes.
        self._regime: dict[str, tuple[datetime, bool | None]] = {}

    async def before_poll(self, papers: list[Paper], poll_started_at: datetime) -> None:
        for timeframe in {p.timeframe for p in papers}:
            latest = await recent_candles(REGIME_ASSET, timeframe, 1)
            if not latest:
                self._regime[timeframe] = (datetime.min, None)
                continue
            cached = self._regime.get(timeframe)
            if cached is not None and cached[0] == latest[-1].open_time:
                continue
            window = bars_for_days(BEAR_SMA_DAYS, timeframe)
            history = await recent_candles(REGIME_ASSET, timeframe, window)
            closes = [float(c.close) for c in history]
            self._regime[timeframe] = (latest[-1].open_time, bear_market(closes, window))

    async def decide(self, tick: Tick) -> Signal | None:
        paper, position = tick.paper, tick.position
        breakout = bars_for_days(BREAKOUT_DAYS, paper.timeframe)
        # Enough for the breakout window plus the ATR warm-up, and the trailing
        # stop's best price since entry (a trend can run for weeks).
        candles = await recent_candles(paper.asset, paper.timeframe, breakout * 4)
        held = None
        if position is not None:
            direction: Direction = "long" if position.direction == "long" else "short"
            held = Held(direction, position.opened_at)
            # Every pass (5 s), so a stop is seen within a minute of the 1m close.
            price = await latest_price(paper.asset, PRICE_INTERVAL)
            if price is not None and stop_loss_hit(direction, position.entry_price, price):
                return Signal("exit", direction, STOP_LOSS)
        bear = self._regime.get(paper.timeframe, (datetime.min, None))[1]
        return decide_signal(_bars(candles), breakout, held, bear)


if __name__ == "__main__":
    run_service("trend-executor", lambda: run(TrendStrategy()))
