"""Keltner strategy executor: the Keltner Channel signals' Buy and Sell
(app/executors/keltner_signals.py). A Buy opens a long, a Sell closes it; a
Sell opens a short, a Buy closes it - each where the paper's direction
allows (both: either). On the signal candle's close, once per signal. No
stop-loss, no take-profit - see docs/keltner-strategy-engine.md. An
averaging paper adds its own rules (LiveGuard, app/executors/keltner_averaging.py).
Run: python -m app.executors.keltner"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db import async_session
from app.execution_engine.models import Position
from app.executors.base import Tick, direction_allowed, last_entry_at, recent_candles, run
from app.executors.keltner_averaging import SWING_STOP, KeltnerGuard, keltner_guard
from app.executors.keltner_signals import keltner_signals
from app.feature_engine.engine import INTERVAL_MINUTES
from app.notifications.error_reporting import run_service
from app.order_queue import Direction, Signal
from app.papers.models import Paper

# Covers the band's warm-up (34 candles) and the EMA's settling.
CANDLE_LOOKBACK = 500

KELTNER_BUY = "keltner_buy"  # a long's entry / a short's exit
KELTNER_SELL = "keltner_sell"  # a short's entry / a long's exit


def reason(signal: Direction) -> str:
    return KELTNER_BUY if signal == "long" else KELTNER_SELL


def decide_signal(
    held: Direction | None,
    signal: Direction | None,
    entered_on_signal: bool,
    paper_direction: str,
) -> Signal | None:
    """The rules, without I/O. `held`: the open position's direction (None
    flat); `signal`: the last closed candle's Buy ("long") / Sell ("short");
    `entered_on_signal`: an entry was already placed since that candle
    closed - one per signal."""
    if held is not None:
        return Signal("exit", held, reason(signal)) if signal and signal != held else None
    if signal is None or entered_on_signal or not direction_allowed(paper_direction, signal):
        return None
    return Signal("enter", signal, reason(signal))


@dataclass(frozen=True)
class LiveGuard:
    """An averaging paper's KeltnerGuard at its last closed candle (base.Guard)."""

    rules: KeltnerGuard
    last: int
    entry: int | None  # the open position's entry candle
    stopped_here: bool  # its last position closed on the swing stop after this candle

    def may_open(self, direction: Direction) -> bool:
        # A swing stop waits for the next signal, not this candle's.
        return not self.stopped_here and self.rules.may_open(direction, self.last)

    def swing_exit(
        self,
        direction: Direction,
        first_price: Decimal,
        entry_price: Decimal,
        size: Decimal,
        realized: Decimal,
    ) -> Signal | None:
        if self.entry is None:
            return None
        sign = 1 if direction == "long" else -1
        close = self.rules.closes[self.last]
        pnl = float(realized) + sign * float(size) * (close - float(entry_price))
        if not self.rules.stopped(direction, self.last, self.entry, float(first_price), pnl):
            return None
        return Signal("exit", direction, SWING_STOP)

    def sell_broken(self, direction: Direction) -> bool:
        return self.entry is not None and self.rules.sell_broken(direction, self.last, self.entry)


async def _stopped_after(paper: Paper, since: datetime) -> bool:
    """The paper's last position (in its mode) closed on the swing stop after `since`."""
    async with async_session() as session:
        last = await session.scalar(
            select(Position)
            .where(
                Position.paper_id == paper.id,
                Position.mode == paper.mode,
                Position.closed_at.is_not(None),
            )
            .order_by(Position.closed_at.desc())
            .limit(1)
        )
    return (
        last is not None
        and last.closed_at is not None
        and last.exit_reason == SWING_STOP
        and last.closed_at >= since
    )


class KeltnerStrategy:
    name = "keltner"

    async def averaging_guard(self, paper: Paper, opened_at: datetime | None) -> LiveGuard | None:
        """base.Guarding: over enough candles to reach back to the open
        position's entry candle."""
        step = timedelta(minutes=INTERVAL_MINUTES[paper.timeframe])
        held = 0 if opened_at is None else int((datetime.now(UTC) - opened_at) / step) + 2
        candles = await recent_candles(paper.asset, paper.timeframe, CANDLE_LOOKBACK + held)
        if len(candles) < 2:
            return None
        rules = keltner_guard(
            paper.direction,
            [float(c.high) for c in candles],
            [float(c.low) for c in candles],
            [float(c.close) for c in candles],
        )
        last = len(candles) - 1
        entry: int | None = None
        if opened_at is not None:
            # The entry candle: the last one closed by the entry.
            closed = [k for k, c in enumerate(candles) if c.open_time + step <= opened_at]
            entry = closed[-1] if closed else 0
        stopped = await _stopped_after(paper, candles[-1].open_time + step)
        return LiveGuard(rules, last, entry, stopped)

    async def before_poll(self, papers: list[Paper], poll_started_at: datetime) -> None:
        return None

    async def decide(self, tick: Tick) -> Signal | None:
        paper, position = tick.paper, tick.position
        candles = await recent_candles(paper.asset, paper.timeframe, CANDLE_LOOKBACK)
        if len(candles) < 2:
            return None
        signal = keltner_signals(
            [float(c.high) for c in candles],
            [float(c.low) for c in candles],
            [float(c.close) for c in candles],
        ).at(len(candles) - 1)
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
    run_service("keltner-executor", lambda: run(KeltnerStrategy()))
