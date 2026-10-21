"""Averaging hedge (docs/papers.md#averaging-hedge-papers), backtest only: an
averaging long on the paper's asset fuelled by a short on HEDGE_ASSET
(app/papers/models.py) - one position per market on the exchange, so the
short can't be on the long's asset. The short is only there to cover the
losing long.

At each candle's close while the long is open (prices: the long's and the
hedge asset's closes; the long's PnL: its whole PnL after fees):

- **Open** - no short, the long asset's trend bands bearish, the pair in loss
  (the long's PnL + its shorts' realized so far) and the long really needing
  support - its margin at least BIG_MARGIN_SHARE of the paper's max margin
  (any, without one): a mirror of the long - its notional at entry on its margin.
- **Close** - the pair's PnL >= 0: the long's PnL + its shorts' - those
  realized so far (reduces, earlier shorts) and the open one's. The shorts'
  profit covers the long's loss, or the long's gain their loss. Only then -
  the short is never closed at a loss of the pair. The long stays open.
- **Half covered** - with the long's and the short's margin together at least
  BIG_MARGIN_SHARE of the paper's max margin, the open short's PnL at least
  HALF_COVER of the long's loss: closed, its profit banked.
- **Top-up** - still bearish, the pair still in loss and the long's notional
  at entry grown (its adds) more than REBALANCE_GAP past the short's: sold
  up to it, its margin up to the long's - each add mirrored. Never once the
  bear phase is over or the pair in profit - the short only fuels a losing long.
- **Reduce** - the long's notional at entry shrank (its units sold) more than
  REBALANCE_GAP under the short's, with the short in profit: bought back
  down to it (the same share of its margin), the profit realized.
- **Margin top-up** - still bearish with the pair in loss: on the candle's
  way up to its high (worst case), each time the short's margin left falls
  to ADD_AT_MARGIN_LEFT, `top_up` of
  margin is added from the budget - the size unchanged, as the long's dip
  adds hold off its margin call - so a bounce in the bear phase doesn't close it.
- **Give-up** - only once the budget can't top it up: the short's margin left
  down to GIVE_UP_AT_MARGIN_LEFT at the candle's high, as the long's
  automatic give-up.
- The long's close closes the short too (at the hedge asset's close).

Each event is a fill of the long's position (side SHORT_*, at the hedge
asset's price). The short's margin counts against the long's budget and its
realized PnL goes into it - the cash for the long's adds. Fees: the long's
rate on every fill."""

from dataclasses import dataclass, field
from datetime import datetime

from app.backtest.bars import Bar, Fill
from app.executors.position_management import ADD_AT_MARGIN_LEFT, GIVE_UP_AT_MARGIN_LEFT
from app.executors.trend_bands import trend_bands

# A short opens only once the long's margin is this share of the max margin
# (the long really needs support); with this share locked by the long and the
# short together, the short closes once its PnL covers HALF_COVER of the long's loss.
BIG_MARGIN_SHARE = 0.2
HALF_COVER = 0.5
# The short is resized once its notional at entry is this far off the long's.
REBALANCE_GAP = 0.05

SHORT_OPEN = "short_open"
SHORT_ADD = "short_add"
SHORT_MARGIN = "short_margin"  # margin added to hold off its give-up, the size unchanged
SHORT_REDUCE = "short_reduce"
SHORT_COVERED = "short_covered"  # the pair's PnL >= 0
SHORT_HALF_COVERED = "short_half_covered"  # big margins, half the long's loss covered
SHORT_GIVE_UP = "short_out_of_margin"
SHORT_WITH_LONG = "short_with_long"  # the long closed
SHORT_SIDES = (
    SHORT_OPEN,
    SHORT_ADD,
    SHORT_MARGIN,
    SHORT_REDUCE,
    SHORT_COVERED,
    SHORT_HALF_COVERED,
    SHORT_GIVE_UP,
    SHORT_WITH_LONG,
)


@dataclass
class Short:
    size: float = 0.0
    cost: float = 0.0  # notional at entry of the size held
    margin: float = 0.0
    fees: float = 0.0  # the size held's entry fees

    @property
    def entry(self) -> float:
        return self.cost / self.size

    def sell(self, price: float, notional: float, margin: float, fee_rate: float) -> None:
        self.size += notional / price
        self.cost += notional
        self.margin += margin
        self.fees += notional * fee_rate

    def pnl(self, price: float, fee_rate: float) -> float:
        """Closed at `price`: net of every fee."""
        return self.cost - self.size * price - self.fees - self.size * price * fee_rate

    def buy_back(
        self, price: float, fraction: float, fee_rate: float
    ) -> tuple[float, float, float]:
        """Buys back `fraction` of the size at `price`: the PnL it realized,
        the margin it released and that size's notional at entry."""
        pnl = self.pnl(price, fee_rate) * fraction
        released = self.margin * fraction
        notional = self.cost * fraction
        self.size -= self.size * fraction
        self.cost -= notional
        self.fees -= self.fees * fraction
        self.margin -= released
        return pnl, released, notional

    def margin_left_at(self, share: float) -> float:
        """The price at which the short's margin left is down to `share` of it."""
        return (self.cost + self.margin * (1 - share)) / self.size

    def give_up_price(self) -> float:
        """Where the short's margin left falls to GIVE_UP_AT_MARGIN_LEFT."""
        return self.margin_left_at(float(GIVE_UP_AT_MARGIN_LEFT))


@dataclass
class Hedge:
    """The hedge of one backtest: the hedge asset's candles and the long
    asset's bearish candles, the margin of a top-up; the short open now."""

    bars: dict[datetime, Bar]  # the hedge asset's, by open time
    bearish: set[datetime]  # the long asset's trend bands bearish at this candle's close
    fee_rate: float
    top_up: float = 0.0  # the margin each top-up adds (the paper's add size); 0: none
    max_margin: float | None = None  # the paper's max margin; None: no half-covered close
    short: Short | None = None
    last_price: float | None = None  # the hedge asset's latest close seen
    fills: list[Fill] = field(default_factory=list)  # the events since the last take

    @property
    def margin(self) -> float:
        return 0.0 if self.short is None else self.short.margin

    def price_at(self, time: datetime) -> float | None:
        """The hedge asset's close at `time`, else the latest one seen."""
        bar = self.bars.get(time)
        return bar.close if bar is not None else self.last_price

    def take_fills(self) -> list[Fill]:
        fills, self.fills = self.fills, []
        return fills

    def close(self, time: datetime, side: str | None, price: float) -> float:
        """Closes the short at `price`; its PnL. `side` None: no fill (valued
        at the last candle, still open)."""
        assert self.short is not None
        pnl, released, notional = self.short.buy_back(price, 1.0, self.fee_rate)
        if side is not None:
            self.fills.append(Fill(time, price, released, notional, side, pnl))
        self.short = None
        return pnl

    def _sell(
        self,
        time: datetime,
        price: float,
        notional: float,
        margin: float,
        can_fund: float,
        side: str,
    ) -> None:
        """Sells `notional` on `margin` - less, at that leverage, if the budget
        can't fund the margin."""
        if margin > can_fund:
            notional, margin = notional * can_fund / margin, can_fund
        if margin <= 0 or notional <= 0:
            return
        if self.short is None:
            self.short = Short()
        self.short.sell(price, notional, margin, self.fee_rate)
        self.fills.append(Fill(time, price, margin, notional, side))

    def step(
        self,
        time: datetime,
        long_pnl: float,
        long_cost: float,
        long_margin: float,
        can_fund: float,
        realized: float = 0.0,
    ) -> float:
        """One candle with the long open: `long_pnl` at its close (after fees),
        `long_cost` (its notional at entry) and `long_margin` - the short
        mirrors both - `can_fund` the budget left for the short's margin,
        `realized` the PnL its shorts realized so far. The PnL realized here."""
        bar = self.bars.get(time)
        if bar is None:
            return 0.0
        self.last_price = bar.close
        losing = time in self.bearish and long_pnl + realized < 0
        if self.short is None:
            needs = self.max_margin is None or long_margin >= BIG_MARGIN_SHARE * self.max_margin
            if losing and needs:
                self._sell(time, bar.close, long_cost, long_margin, can_fund, SHORT_OPEN)
            return 0.0
        # On the way up to the high, in the bear phase with the pair in loss: a
        # top-up at each half of the margin lost, while the budget funds it;
        # the give-up only past them.
        while losing and self.top_up > 0 and self.top_up <= can_fund:
            at = self.short.margin_left_at(float(ADD_AT_MARGIN_LEFT))
            if bar.high < at:
                break
            self.short.margin += self.top_up
            can_fund -= self.top_up
            self.fills.append(Fill(time, max(at, bar.open), self.top_up, 0.0, SHORT_MARGIN))
        level = self.short.give_up_price()
        if bar.high >= level:
            return self.close(time, SHORT_GIVE_UP, max(level, bar.open))
        short_pnl = self.short.pnl(bar.close, self.fee_rate)
        if long_pnl + realized + short_pnl >= 0:
            return self.close(time, SHORT_COVERED, bar.close)
        big = (
            self.max_margin is not None
            and long_margin + self.short.margin >= BIG_MARGIN_SHARE * self.max_margin
        )
        if big and long_pnl < 0 and short_pnl >= HALF_COVER * -long_pnl:
            return self.close(time, SHORT_HALF_COVERED, bar.close)
        cost = self.short.cost
        if losing and long_cost > cost * (1 + REBALANCE_GAP):
            notional = long_cost - cost
            # The margin up to the long's - at least the long's leverage on the notional.
            margin = max(long_margin - self.short.margin, notional * long_margin / long_cost)
            self._sell(time, bar.close, notional, margin, can_fund, SHORT_ADD)
        elif (
            long_cost < cost * (1 - REBALANCE_GAP) and self.short.pnl(bar.close, self.fee_rate) > 0
        ):
            fraction = 1 - long_cost / cost
            pnl, released, notional = self.short.buy_back(bar.close, fraction, self.fee_rate)
            self.fills.append(Fill(time, bar.close, released, notional, SHORT_REDUCE, pnl))
            return pnl
        return 0.0


def bearish_candles(bars: list[Bar]) -> set[datetime]:
    """The candles the trend bands close bearish on."""
    b = trend_bands(
        [x.high for x in bars],
        [x.low for x in bars],
        [x.close for x in bars],
        [x.volume for x in bars],
    )
    return {bar.time for bar, state in zip(bars, b.state, strict=True) if state == -1}
