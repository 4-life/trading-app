"""Paper-level position management (docs/papers.md#averaging-papers),
shared by every executor through the executor loop: averaging down, a
max-drawdown give-up, and the take-profit floor under the strategy's sell
signals, from the paper's own parameters. Pure - prices in, a signal out."""

from collections.abc import Iterable
from decimal import Decimal

from app.config import settings
from app.order_queue import Direction, Signal
from app.papers.models import Paper

# A strategy's sell taken with the gain at least take_profit_pct: "take_profit:<its reason>".
TAKE_PROFIT_EXIT = "take_profit"
MAX_DRAWDOWN_EXIT = "max_drawdown"  # the price moved max_drawdown_pct against the first buy
# The automatic give-up: the adds couldn't keep up (max margin reached, no
# cash) and the margin left fell to GIVE_UP_AT_MARGIN_LEFT - just before the
# exchange's liquidation (MAINTENANCE_MARGIN_PCT, 20% left).
OUT_OF_MARGIN_EXIT = "out_of_margin"
AVERAGE_DOWN = "average_down"  # a unit added: the margin left fell to ADD_AT_MARGIN_LEFT
# A unit added at the strategy's entry signal while the position is open.
SIGNAL_ADD = "signal_add"
# An intraday paper with reopen_in_trend: a fresh position opened at the close
# of the candle its take-profit hit on, while the strategy's own trade (its
# trend) is still open there.
REOPEN_IN_TREND = "reopen_in_trend"
# A unit sold (a partial close) at the next-higher unit's price (unwind_level)
# - never the lowest one held: it's kept to the position's close.
UNWIND_EXIT = "unwind_adds"
# A unit is sold at least this far above its own price - its slippage and a
# small gain on top of what it covers - plus both fees.
UNWIND_MARKUP = Decimal("0.004")
# An averaging paper adds a unit once its loss has taken this share of the
# margin put in - halfway to the margin call (MAINTENANCE_MARGIN_PCT, 20% left).
ADD_AT_MARGIN_LEFT = Decimal("0.5")
# An add puts the margin left back above ADD_AT_MARGIN_LEFT: it only falls
# this far once no add came - the position closes before it's liquidated.
GIVE_UP_AT_MARGIN_LEFT = Decimal("0.3")
# The two above are where the margin call is at MAINTENANCE_MARGIN_PCT (20%
# left). The exchange's maintenance margin, a share of the notional, can
# liquidate sooner - ENA's 6% at 10x with 60% left: the levels move up with it,
# kept at the same place between the liquidation and the entry (margin_levels).
DEFAULT_LIQUIDATION_LEFT = settings.maintenance_margin_pct


def add_terms(paper: Paper, reason: str) -> tuple[Decimal, Decimal] | None:
    """An add's (margin, leverage): a signal add - the strategy's entry signal
    - is sized like the first entry (the initial size at the paper's
    leverage); a dip add - holding off the margin call - at the add size
    (default: the initial size) and the add leverage. None if the paper
    doesn't set them."""
    margin: Decimal | None
    leverage: Decimal | None
    if reason == SIGNAL_ADD:
        margin, leverage = paper.initial_size_usd, paper.leverage
    else:
        margin = paper.add_size_usd if paper.add_size_usd is not None else paper.initial_size_usd
        leverage = paper.add_leverage
    if margin is None or leverage is None:
        return None
    return margin, leverage


def stops_paper(paper: Paper, reason: str) -> bool:
    """An averaging paper stops - disables itself - once its take-profit has
    closed the position: the owner enables it again at the next bottom. An
    intraday one keeps running."""
    return (
        paper.kind == "averaging"
        and not paper.intraday
        and reason.split(":")[0] == TAKE_PROFIT_EXIT
    )


def _profit_reached(
    direction: Direction,
    price: Decimal,
    entry_price: Decimal,
    size: Decimal,
    margin: Decimal,
    realized: Decimal,
    take_profit_pct: Decimal,
) -> bool:
    """The position's whole PnL at `price` - `realized` by its unwinds plus the
    size held - is at least `take_profit_pct` of the margin backing it. The
    unwinds are booked against the average entry, which they don't move: the
    size held can be above that average and the position still in loss."""
    sign = 1 if direction == "long" else -1
    return realized + sign * size * (price - entry_price) >= take_profit_pct * margin


def take_profit_close(
    direction: Direction,
    price: Decimal,
    entry_price: Decimal,
    size: Decimal,
    margin: Decimal,
    realized: Decimal,
    take_profit_pct: Decimal | None,
) -> Signal | None:
    """An intraday paper's take-profit: the position closes as soon as its
    whole PnL reaches `take_profit_pct` of its margin - no strategy sell."""
    if take_profit_pct is None or not _profit_reached(
        direction, price, entry_price, size, margin, realized, take_profit_pct
    ):
        return None
    return Signal("exit", direction, TAKE_PROFIT_EXIT)


def dead_close(
    direction: Direction,
    price: Decimal,
    entry_price: Decimal,
    size: Decimal,
    margin: Decimal,
    realized: Decimal,
    floor: Decimal,
    reason: str,
) -> Signal | None:
    """A dead position's close (app/executors/keltner_averaging.py): as soon
    as its whole PnL at `price` is back up at `floor` of the margin backing it."""
    if not _profit_reached(direction, price, entry_price, size, margin, realized, floor):
        return None
    return Signal("exit", direction, reason)


def take_profit_sell(
    sell: Signal,
    price: Decimal,
    entry_price: Decimal,
    size: Decimal,
    margin: Decimal,
    realized: Decimal,
    take_profit_pct: Decimal | None,
) -> Signal | None:
    """The strategy's `sell` (an exit) as the position's close - only with the
    position's whole PnL at `price` at least `take_profit_pct` of the margin
    backing it (_profit_reached: the take-profit is a floor, not an exit of
    its own); else None, and the position holds."""
    if sell.signal != "exit" or take_profit_pct is None:
        return None
    if not _profit_reached(
        sell.direction, price, entry_price, size, margin, realized, take_profit_pct
    ):
        return None
    return Signal("exit", sell.direction, f"{TAKE_PROFIT_EXIT}:{sell.reason}")


# A unit of the grid: (buy price, size) - Decimal live, float in the backtest.


def held_units[N: (float, Decimal)](
    sign: int, fills: Iterable[tuple[str, N, N]]
) -> list[tuple[N, N]]:
    """The units still held, from the position's fills (oldest first, as
    (side, price, size)): every buy is a unit - the first, every dip add and
    signal add; every sell (an unwind) sold the one unwound_unit picks.
    `sign`: 1 a long, -1 a short."""
    units: list[tuple[N, N]] = []
    for side, price, size in fills:
        if side == "sell":
            unit = unwound_unit(sign, units)
            if unit is not None:
                units.remove(unit)
        else:
            units.append((price, size))
    return units


def unwound_unit[N: (float, Decimal)](sign: int, units: list[tuple[N, N]]) -> tuple[N, N] | None:
    """The unit the next unwind sells: the lowest but the lowest - kept to the
    position's close (a short: mirrored); None with fewer than two."""
    if len(units) < 2:
        return None
    return sorted(units, key=lambda unit: sign * unit[0])[1]


def unwind_level[N: (float, Decimal)](sign: int, units: list[tuple[N, N]], buffer: N) -> N | None:
    """The price the next unwind sells at: the next-higher unit's buy price;
    the highest unit's, half the way from the lowest above it - never under
    its own price plus `buffer` (unwind_buffer: its fees, slippage, a gain),
    so no sale loses. None with nothing to sell. A short: mirrored."""
    unit = unwound_unit(sign, units)
    if unit is None:
        return None
    price = unit[0]
    above = [p for p, _ in units if sign * p > sign * price]
    if above:
        level = min(above, key=lambda p: sign * p)
    else:
        lowest = min((p for p, _ in units), key=lambda p: sign * p)
        level = price + (price - lowest) / 2
    floor = price * (1 + sign * buffer)
    return max(level, floor, key=lambda p: sign * p)


def unwind_buffer(fee_rate: Decimal) -> Decimal:
    """How far above its own price a unit is sold at least: UNWIND_MARKUP
    plus the fee of both its buy and its sell (`fee_rate`: per side)."""
    return UNWIND_MARKUP + 2 * fee_rate


def next_unwind(
    direction: Direction,
    price: Decimal,
    units: list[tuple[Decimal, Decimal]],
    size: Decimal,
    buffer: Decimal,
) -> Signal | None:
    """The next unwind (unwound_unit, at unwind_level) once `price` is there:
    its unit's share of the position's `size`."""
    sign = 1 if direction == "long" else -1
    unit = unwound_unit(sign, units)
    level = unwind_level(sign, units, buffer)
    if unit is None or level is None or sign * (price - level) < 0:
        return None
    return Signal("exit", direction, UNWIND_EXIT, close_fraction=min(unit[1] / size, Decimal(1)))


def signal_add(entry: Signal | None, direction: Direction) -> Signal | None:
    """The strategy's `entry` signal (in the position's direction) while a
    position is open adds a unit - above or below its entry; the dip adds
    hold off the margin call, the take-profit closes it. Else None."""
    if entry is None or entry.signal != "enter" or entry.direction != direction:
        return None
    return Signal("add", direction, SIGNAL_ADD)


def margin_levels(
    margin: float, notional: float, maintenance_notional: float | None
) -> tuple[float, float]:
    """The (add, give-up) shares of the margin left: where ADD_AT_MARGIN_LEFT
    and GIVE_UP_AT_MARGIN_LEFT sit between the liquidation and the entry,
    the liquidation being the exchange's - its maintenance margin
    (`maintenance_notional`) x the position's `notional` at entry - when
    that comes before DEFAULT_LIQUIDATION_LEFT. The defaults otherwise."""
    base = DEFAULT_LIQUIDATION_LEFT
    liquidation = base
    if maintenance_notional is not None and margin > 0:
        liquidation = min(max(base, maintenance_notional * notional / margin), 1.0)
    scale = (1 - liquidation) / (1 - base)
    return (
        liquidation + (float(ADD_AT_MARGIN_LEFT) - base) * scale,
        liquidation + (float(GIVE_UP_AT_MARGIN_LEFT) - base) * scale,
    )


def margin_left(
    direction: Direction, price: Decimal, entry_price: Decimal, size: Decimal, margin: Decimal
) -> Decimal:
    """The share of the margin the position's loss at `price` hasn't taken yet."""
    sign = 1 if direction == "long" else -1
    return (margin + sign * size * (price - entry_price)) / margin


def managed_signal(
    direction: Direction,
    price: Decimal,
    entry_price: Decimal,
    size: Decimal,
    margin: Decimal,
    first_buy: Decimal,
    max_drawdown_pct: Decimal | None,
    maintenance_notional: float | None = None,
) -> Signal | None:
    """An averaging position's give-ups or next add at `price`, in that
    order; None when none is due. `entry_price`: the average entry;
    `first_buy`: the fill of its first buy. The optional `max_drawdown_pct`
    give-up against the first buy; the automatic one once the margin left
    is down to the give-up level (the adds stopped - before the
    liquidation); else a unit added once it falls to the add level - both
    from margin_levels, the exchange's `maintenance_notional` moving them up.
    A short is mirrored."""
    sign = 1 if direction == "long" else -1
    drawdown = sign * (first_buy - price) / first_buy  # against the first buy
    if max_drawdown_pct is not None and drawdown >= max_drawdown_pct:
        return Signal("exit", direction, MAX_DRAWDOWN_EXIT)
    left = margin_left(direction, price, entry_price, size, margin)
    add_at, give_up_at = margin_levels(
        float(margin), float(size * entry_price), maintenance_notional
    )
    if left <= Decimal(str(give_up_at)):
        return Signal("exit", direction, OUT_OF_MARGIN_EXIT)
    if left <= Decimal(str(add_at)):
        return Signal("add", direction, AVERAGE_DOWN)
    return None
