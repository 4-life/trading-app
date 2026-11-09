"""A Keltner averaging paper's own rules - see
docs/keltner-strategy-engine.md#averaging. Pure, indexed by candle; live
(app/executors/keltner.py, through base._averaging) and the averaging
backtest (app/backtest/averaging.py) use the same.

- Entry: a Keltner Buy with the Supertrend red opens a long, a Sell with it
  green a short (the paper's Supertrend, as charted: the upper trendline's
  for a short paper, the lower's for the others). Signal adds take any.
- Broken sell: the position's first exit signal since its entry is ignored
  while the Supertrend's line is still where it was at the entry.
- Core: the first entry and the strength adds are never unwound
  (position_management's grid with a core); the dip and signal adds are.
- Signal adds: at most MAX_SIGNAL_ADDS, each SIGNAL_ADD_SPACING below the
  last buy at least (a short: above).
- Strength add: a core unit, sized like the first entry, on the candle the
  Supertrend flips the position's way (a long: green) with the position in
  profit at its close."""

from dataclasses import dataclass
from datetime import datetime

from app.executors.keltner_signals import keltner_signals
from app.executors.supertrend import signals as supertrend_signals

MAX_SIGNAL_ADDS = 5  # a position's signal adds
SIGNAL_ADD_SPACING = 0.01  # a signal add's distance below the last buy at least (a short: above)


def _sign(direction: str) -> int:
    return 1 if direction == "long" else -1


@dataclass(frozen=True)
class KeltnerGuard:
    """Per candle, oldest first."""

    closes: list[float]
    trend: list[int | None]  # the Supertrend's: 1 green, -1 red
    line: list[float | None]  # its line
    buy: list[bool]  # Keltner's Buy
    sell: list[bool]  # Keltner's Sell

    def may_open(self, direction: str, i: int) -> bool:
        """A long only on a red Supertrend, a short only on a green one."""
        return self.trend[i] == -_sign(direction)

    def signal_add_allowed(self, direction: str, i: int, last_buy: float, signal_adds: int) -> bool:
        """Candle `i`'s signal add (at its close): under MAX_SIGNAL_ADDS so far
        (`signal_adds`), SIGNAL_ADD_SPACING below the `last_buy` at least."""
        sign = _sign(direction)
        level = last_buy * (1 - sign * SIGNAL_ADD_SPACING)
        return signal_adds < MAX_SIGNAL_ADDS and sign * (self.closes[i] - level) <= 0

    def strength_add(self, direction: str, i: int, pnl: float) -> bool:
        """The Supertrend flipped the position's way at candle `i`'s close,
        with its whole PnL there (`pnl`) in profit."""
        sign = _sign(direction)
        return i >= 1 and self.trend[i] == sign and self.trend[i - 1] == -sign and pnl > 0

    def sell_broken(self, direction: str, i: int, entry: int) -> bool:
        """Candle `i`'s exit signal (a long's Sell, a short's Buy) is the
        position's first since its entry candle, with the Supertrend's line
        still where it was at the entry - ignored."""
        exits = self.sell if direction == "long" else self.buy
        first = not any(exits[entry + 1 : i])
        return first and self.line[i] == self.line[entry]


def average_cycle_move(
    guard: KeltnerGuard, times: list[datetime], since: datetime
) -> tuple[float | None, int]:
    """The average distance (a share of the price, up or down alike) from a
    good entry - from `since`, a Buy on a red Supertrend - to the next good sell,
    a Sell on a green one; then the next cycle. And how many cycles: a cycle
    still open is left out, without any the average is None."""
    moves: list[float] = []
    entry: int | None = None
    for i, time in enumerate(times):
        if time < since:
            continue
        if entry is None:
            if guard.buy[i] and guard.trend[i] == -1:
                entry = i
        elif guard.sell[i] and guard.trend[i] == 1:
            moves.append(abs(guard.closes[i] / guard.closes[entry] - 1))
            entry = None
    return (sum(moves) / len(moves) if moves else None), len(moves)


def keltner_guard(
    paper_direction: str, highs: list[float], lows: list[float], closes: list[float]
) -> KeltnerGuard:
    st = supertrend_signals(highs, lows, closes, "short" if paper_direction == "short" else "long")
    ks = keltner_signals(highs, lows, closes)
    return KeltnerGuard(closes, st.trend, st.line, ks.buy, ks.sell)
