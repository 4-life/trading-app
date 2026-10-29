"""Keltner strategy executor: the Keltner Channel signals' Buy and Sell
(app/executors/keltner_signals.py). A long paper buys on a Buy and closes on
a Sell; a short paper sells on a Sell and closes on a Buy. On the signal
candle's close, once per signal. No stop-loss, no take-profit - see
docs/keltner-strategy-engine.md.
Run: python -m app.executors.keltner"""

from datetime import datetime, timedelta

from app.executors.base import Tick, last_entry_at, recent_candles, run
from app.executors.keltner_signals import keltner_signals
from app.feature_engine.engine import INTERVAL_MINUTES
from app.notifications.error_reporting import run_service
from app.order_queue import Direction, Signal
from app.papers.models import Paper

# Covers the band's warm-up (34 candles) and the EMA's settling.
CANDLE_LOOKBACK = 500

KELTNER_BUY = "keltner_buy"  # a long's entry / a short's exit
KELTNER_SELL = "keltner_sell"  # a short's entry / a long's exit


def decide_signal(
    direction: Direction, held: bool, buy: bool, sell: bool, entered_on_signal: bool
) -> Signal | None:
    """The rules, without I/O. `direction`: the paper's (long or short);
    `held`: a position is open; `buy` / `sell`: the signal on the last
    closed candle; `entered_on_signal`: an entry was already placed since
    that candle closed - one per signal."""
    long = direction == "long"
    opens, closes = (buy, sell) if long else (sell, buy)
    if held:
        if not closes:
            return None
        return Signal("exit", direction, KELTNER_SELL if long else KELTNER_BUY)
    if opens and not entered_on_signal:
        return Signal("enter", direction, KELTNER_BUY if long else KELTNER_SELL)
    return None


class KeltnerStrategy:
    name = "keltner"

    async def before_poll(self, papers: list[Paper], poll_started_at: datetime) -> None:
        return None

    async def decide(self, tick: Tick) -> Signal | None:
        paper, position = tick.paper, tick.position
        direction: Direction = "long" if paper.direction == "long" else "short"
        candles = await recent_candles(paper.asset, paper.timeframe, CANDLE_LOOKBACK)
        if len(candles) < 2:
            return None
        ks = keltner_signals(
            [float(c.high) for c in candles],
            [float(c.low) for c in candles],
            [float(c.close) for c in candles],
        )
        buy, sell = ks.buy[-1], ks.sell[-1]
        entered = False
        if position is None and (buy if direction == "long" else sell):
            step = timedelta(minutes=INTERVAL_MINUTES[paper.timeframe])
            last_entry = await last_entry_at(paper, direction=direction)
            entered = last_entry is not None and last_entry >= candles[-1].open_time + step
        return decide_signal(direction, position is not None, buy, sell, entered)


if __name__ == "__main__":
    run_service("keltner-executor", lambda: run(KeltnerStrategy()))
