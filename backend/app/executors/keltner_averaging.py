"""A Keltner averaging paper's own rules - see
docs/keltner-strategy-engine.md#averaging. Pure, indexed by candle; live
(app/executors/keltner.py, through base._averaging) and the averaging
backtest (app/backtest/averaging.py) use the same.

- Entry: a Keltner Buy with the Supertrend red opens a long, a Sell with it
  green a short (the paper's Supertrend, as charted: the lower trendline's
  for a long paper, the upper's for the others). Signal adds take any.
- Dead: a position in loss whose candle closes below the last confirmed LL
  (a short: above the last confirmed HH) is dead - it keeps averaging and
  closes once its whole PnL is back up at DEAD_CLOSE_PNL_USD (dead_close;
  before fees and slippage). One that opened beyond that swing waits
  for the next one confirmed after its entry.
- Broken sell: the position's first exit signal since its entry is ignored
  while the Supertrend's line is still where it was at the entry."""

from dataclasses import dataclass

from app.executors.keltner_signals import keltner_signals
from app.executors.supertrend import signals as supertrend_signals
from app.executors.swings import find_swings

DEAD_EXIT = "dead_close"  # exit reason: a dead position back up at DEAD_CLOSE_PNL_USD
DEAD_CLOSE_PNL_USD = -20.0  # a dead position's whole PnL it closes at


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
    # The last LL / HH confirmed by this candle's close: its price and the
    # candle that confirmed it.
    low: list[tuple[float, int] | None]
    high: list[tuple[float, int] | None]

    def may_open(self, direction: str, i: int) -> bool:
        """A long only on a red Supertrend, a short only on a green one."""
        return self.trend[i] == -_sign(direction)

    def stop(self, direction: str, i: int, entry: int, entry_price: float) -> float | None:
        """The swing a position opened at candle `entry`, at `entry_price`,
        closes beyond at candle `i` - None while there's none: the last one
        confirmed is broken already if the entry was beyond it."""
        swing = self.low[i] if direction == "long" else self.high[i]
        if swing is None:
            return None
        price, confirmed = swing
        if confirmed <= entry and _sign(direction) * (entry_price - price) < 0:
            return None
        return price

    def dies(self, direction: str, i: int, entry: int, entry_price: float, pnl: float) -> bool:
        """The position's whole PnL at candle `i`'s close (`pnl`) is negative
        and that close is beyond its swing."""
        level = self.stop(direction, i, entry, entry_price)
        return level is not None and pnl < 0 and _sign(direction) * (self.closes[i] - level) < 0

    def sell_broken(self, direction: str, i: int, entry: int) -> bool:
        """Candle `i`'s exit signal (a long's Sell, a short's Buy) is the
        position's first since its entry candle, with the Supertrend's line
        still where it was at the entry - ignored."""
        exits = self.sell if direction == "long" else self.buy
        first = not any(exits[entry + 1 : i])
        return first and self.line[i] == self.line[entry]


def keltner_guard(
    paper_direction: str, highs: list[float], lows: list[float], closes: list[float]
) -> KeltnerGuard:
    st = supertrend_signals(highs, lows, closes, "long" if paper_direction == "long" else "short")
    ks = keltner_signals(highs, lows, closes)
    confirmed: dict[str, dict[int, float]] = {"LL": {}, "HH": {}}
    for s in find_swings(highs, lows):
        if s.kind in confirmed:
            confirmed[s.kind][s.confirm_index] = s.price
    low: list[tuple[float, int] | None] = []
    high: list[tuple[float, int] | None] = []
    for i in range(len(closes)):
        last_low = low[-1] if low else None
        last_high = high[-1] if high else None
        low.append((confirmed["LL"][i], i) if i in confirmed["LL"] else last_low)
        high.append((confirmed["HH"][i], i) if i in confirmed["HH"] else last_high)
    return KeltnerGuard(closes, st.trend, st.line, ks.buy, ks.sell, low, high)
