"""A single paper's own stop-loss and take-profit (`stop_loss_pct`,
`price_take_profit_pct` - shares of the entry price), on top of whatever
its strategy does: the shared executor loop closes a position that reaches
either one before asking the strategy, and an entry carries their prices
(the tighter stop, the nearer take-profit, against the strategy's own) -
docs/papers.md#stop-loss-and-take-profit. Pure."""

from dataclasses import replace
from decimal import Decimal

from app.order_queue import Direction, Signal
from app.papers.models import Paper

PAPER_STOP_LOSS = "paper_stop_loss"
PAPER_TAKE_PROFIT = "paper_take_profit"


def levels(
    paper: Paper, direction: Direction, entry: Decimal
) -> tuple[Decimal | None, Decimal | None]:
    """The paper's stop-loss and take-profit prices for an entry at `entry`."""
    sign = 1 if direction == "long" else -1
    stop = take = None
    if paper.stop_loss_pct is not None:
        stop = entry * (1 - sign * paper.stop_loss_pct)
    if paper.price_take_profit_pct is not None:
        take = entry * (1 + sign * paper.price_take_profit_pct)
    return stop, take


def paper_exit(paper: Paper, direction: Direction, entry: Decimal, price: Decimal) -> Signal | None:
    """The exit of an open position whose price reached the paper's
    stop-loss or take-profit; None otherwise."""
    stop, take = levels(paper, direction, entry)
    sign = 1 if direction == "long" else -1
    if stop is not None and sign * price <= sign * stop:
        return Signal("exit", direction, PAPER_STOP_LOSS)
    if take is not None and sign * price >= sign * take:
        return Signal("exit", direction, PAPER_TAKE_PROFIT)
    return None


def with_paper_levels(paper: Paper, signal: Signal, price: Decimal) -> Signal:
    """An entry with the paper's levels at `price` - against the strategy's
    own, the tighter stop and the nearer take-profit."""
    stop, take = levels(paper, signal.direction, price)
    if stop is None and take is None:
        return signal
    long = signal.direction == "long"
    own_stop, own_take = signal.stop_loss_price, signal.take_profit_price
    if stop is not None and own_stop is not None:
        stop = max(stop, own_stop) if long else min(stop, own_stop)
    if take is not None and own_take is not None:
        take = min(take, own_take) if long else max(take, own_take)
    return replace(
        signal,
        stop_loss_price=stop if stop is not None else own_stop,
        take_profit_price=take if take is not None else own_take,
    )
