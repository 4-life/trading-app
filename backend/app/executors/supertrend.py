"""Supertrend strategy executor: the Supertrend on the Trendlines with Breaks
lines (app/executors/supertrend_signals.py). A long paper buys on a Buy of
the one on the lower line and closes on its Sell; a short paper sells on a
Sell of the one on the upper line and closes on its Buy. On the signal
candle's close, once per signal. No stop-loss, no take-profit - see
docs/supertrend-strategy-engine.md.
Run: python -m app.executors.supertrend"""

from datetime import datetime, timedelta

from app.executors.base import Tick, last_entry_at, recent_candles, run
from app.executors.supertrend_signals import Supertrend, trendline_supertrends
from app.feature_engine.engine import INTERVAL_MINUTES
from app.notifications.error_reporting import run_service
from app.order_queue import Direction, Signal
from app.papers.models import Paper

# Covers the trendlines' pivots (14 candles each side) and both ATR warm-ups.
CANDLE_LOOKBACK = 500

SUPERTREND_BUY = "supertrend_buy"  # a long's entry / a short's exit
SUPERTREND_SELL = "supertrend_sell"  # a short's entry / a long's exit


def signals(
    highs: list[float], lows: list[float], closes: list[float], direction: Direction
) -> Supertrend:
    """The Supertrend a paper trades: on the lower trendline for a long one,
    the upper for a short one."""
    upper, lower = trendline_supertrends(highs, lows, closes)
    return lower if direction == "long" else upper


def decide_signal(
    direction: Direction, held: bool, buy: bool, sell: bool, entered_on_signal: bool
) -> Signal | None:
    """The rules, without I/O. `direction`: the paper's (long or short);
    `held`: a position is open; `buy` / `sell`: its Supertrend's signal on
    the last closed candle; `entered_on_signal`: an entry was already placed
    since that candle closed - one per signal."""
    long = direction == "long"
    opens, closes = (buy, sell) if long else (sell, buy)
    if held:
        if not closes:
            return None
        return Signal("exit", direction, SUPERTREND_SELL if long else SUPERTREND_BUY)
    if opens and not entered_on_signal:
        return Signal("enter", direction, SUPERTREND_BUY if long else SUPERTREND_SELL)
    return None


class SupertrendStrategy:
    name = "supertrend"

    async def before_poll(self, papers: list[Paper], poll_started_at: datetime) -> None:
        return None

    async def decide(self, tick: Tick) -> Signal | None:
        paper, position = tick.paper, tick.position
        direction: Direction = "long" if paper.direction == "long" else "short"
        candles = await recent_candles(paper.asset, paper.timeframe, CANDLE_LOOKBACK)
        if len(candles) < 2:
            return None
        st = signals(
            [float(c.high) for c in candles],
            [float(c.low) for c in candles],
            [float(c.close) for c in candles],
            direction,
        )
        buy, sell = st.buy[-1], st.sell[-1]
        entered = False
        if position is None and (buy if direction == "long" else sell):
            step = timedelta(minutes=INTERVAL_MINUTES[paper.timeframe])
            last_entry = await last_entry_at(paper, direction=direction)
            entered = last_entry is not None and last_entry >= candles[-1].open_time + step
        return decide_signal(direction, position is not None, buy, sell, entered)


if __name__ == "__main__":
    run_service("supertrend-executor", lambda: run(SupertrendStrategy()))
