"""VWAP + EMA9 strategy executor - the signals alone: a BUY (the close moved
above both the session VWAP and EMA 9) opens a long, a SELL (below both)
closes it; with direction both, a SELL also opens a short and a BUY closes
it. On the signal candle's close, once per signal. No stop-loss, no zones -
see docs/vwap-strategy-engine.md.
Run: python -m app.executors.vwap"""

from datetime import datetime, timedelta

from app.executors.base import Tick, direction_allowed, last_entry_at, recent_candles, run
from app.executors.vwap_signals import lines, signal_at
from app.feature_engine.engine import INTERVAL_MINUTES
from app.notifications.error_reporting import run_service
from app.order_queue import Direction, Signal
from app.papers.models import Paper

CANDLE_LOOKBACK = 500  # covers the session (UTC day) and the EMA warm-up

BUY_SIGNAL = "buy_signal"  # a long's entry / a short's exit
SELL_SIGNAL = "sell_signal"  # a short's entry / a long's exit


def reason(signal: Direction) -> str:
    return BUY_SIGNAL if signal == "long" else SELL_SIGNAL


def decide_signal(
    held: Direction | None,
    signal: Direction | None,
    entered_on_signal: bool,
    paper_direction: str,
) -> Signal | None:
    """The rules, without I/O. `held`: the open position's direction (None
    flat); `signal`: the last closed candle's BUY ("long") / SELL ("short");
    `entered_on_signal`: an entry was already placed since that candle
    closed - one per signal."""
    if held is not None:
        return Signal("exit", held, reason(signal)) if signal and signal != held else None
    if signal is None or entered_on_signal or not direction_allowed(paper_direction, signal):
        return None
    return Signal("enter", signal, reason(signal))


class VwapStrategy:
    name = "vwap"

    async def before_poll(self, papers: list[Paper], poll_started_at: datetime) -> None:
        return None

    async def decide(self, tick: Tick) -> Signal | None:
        paper, position = tick.paper, tick.position
        candles = await recent_candles(paper.asset, paper.timeframe, CANDLE_LOOKBACK)
        if len(candles) < 2:
            return None
        closes = [float(c.close) for c in candles]
        ln = lines(
            [c.open_time for c in candles],
            [float(c.high) for c in candles],
            [float(c.low) for c in candles],
            closes,
            [float(c.volume) for c in candles],
        )
        signal = signal_at(closes, ln, len(candles) - 1)
        held: Direction | None = None
        if position is not None:
            held = "long" if position.direction == "long" else "short"
        entered = False
        if held is None and signal is not None:
            step = timedelta(minutes=INTERVAL_MINUTES[paper.timeframe])
            last_entry = await last_entry_at(paper, direction=signal)
            entered = last_entry is not None and last_entry >= candles[-1].open_time + step
        return decide_signal(held, signal, entered, paper.direction)


if __name__ == "__main__":
    run_service("vwap-executor", lambda: run(VwapStrategy()))
