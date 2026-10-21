"""Demo fill math - pure functions, no I/O (docs/execution-engine.md#demo-execution)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Quote:
    """Best bid / ask of the provider's order book at fill time."""

    bid: Decimal
    ask: Decimal

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2


def fill_price(quote: Quote, side: str) -> Decimal:
    """A market order crosses the spread: buys fill at the ask, sells at the bid."""
    return quote.ask if side == "buy" else quote.bid


def open_side(direction: str) -> str:
    return "buy" if direction == "long" else "sell"


def close_side(direction: str) -> str:
    return "sell" if direction == "long" else "buy"


@dataclass(frozen=True)
class OpenFill:
    price: Decimal
    size: Decimal
    margin_usd: Decimal
    fee_usd: Decimal


def open_fill(
    direction: str, notional_usd: Decimal, leverage: Decimal, quote: Quote, fee_rate: Decimal
) -> OpenFill:
    """`notional_usd` is the position's exposure; the margin reserved is
    notional / leverage. `fee_rate`: the provider's taker fee."""
    price = fill_price(quote, open_side(direction))
    return OpenFill(
        price=price,
        size=notional_usd / price,
        margin_usd=notional_usd / leverage,
        fee_usd=notional_usd * fee_rate,
    )


@dataclass(frozen=True)
class Grown:
    """A position after an add (averaging down)."""

    size: Decimal
    entry_price: Decimal  # the average entry
    margin_usd: Decimal
    leverage: Decimal  # the whole position's: notional at entry / margin


def grow(
    size: Decimal,
    entry_price: Decimal,
    margin_usd: Decimal,
    add_size: Decimal,
    add_price: Decimal,
    add_margin_usd: Decimal,
) -> Grown:
    """The position after adding `add_size` at `add_price` with `add_margin_usd`."""
    total = size + add_size
    notional = size * entry_price + add_size * add_price
    margin = margin_usd + add_margin_usd
    return Grown(total, notional / total, margin, notional / margin)


def funding_paid(
    direction: str,
    size: Decimal,
    entry_price: Decimal,
    rates: Sequence[tuple[datetime, Decimal]],
    opened_at: datetime,
    closed_at: datetime,
) -> Decimal:
    """Funding paid while the position was open (negative = received).
    Longs pay positive rates, shorts receive them."""
    total_rate = sum((r for ts, r in rates if opened_at < ts <= closed_at), Decimal(0))
    sign = 1 if direction == "long" else -1
    return sign * total_rate * size * entry_price


@dataclass(frozen=True)
class CloseFill:
    price: Decimal
    fee_usd: Decimal
    funding_usd: Decimal
    # Price move minus exit fee and funding - what comes back on top of the margin.
    settlement_pnl_usd: Decimal


def close_fill(
    direction: str,
    size: Decimal,
    entry_price: Decimal,
    quote: Quote,
    funding_usd: Decimal,
    fee_rate: Decimal,
) -> CloseFill:
    price = fill_price(quote, close_side(direction))
    sign = 1 if direction == "long" else -1
    fee = size * price * fee_rate
    gross = sign * (price - entry_price) * size
    return CloseFill(
        price=price,
        fee_usd=fee,
        funding_usd=funding_usd,
        settlement_pnl_usd=gross - fee - funding_usd,
    )


def unrealized_pnl(direction: str, entry_price: Decimal, price: Decimal, size: Decimal) -> Decimal:
    sign = 1 if direction == "long" else -1
    return sign * (price - entry_price) * size


def liquidation_due(
    direction: str,
    entry_price: Decimal,
    size: Decimal,
    margin_usd: Decimal,
    price: Decimal,
    maintenance_margin_pct: Decimal,
) -> bool:
    """True once the remaining margin (margin + unrealized PnL) is at or
    below the maintenance share of the initial margin."""
    remaining = margin_usd + unrealized_pnl(direction, entry_price, price, size)
    return remaining <= margin_usd * maintenance_margin_pct


def profitability_pct(realized_pnl_usd: Decimal, margin_used_usd: Decimal) -> Decimal:
    """Realized PnL as a percentage of the margin used."""
    if margin_used_usd <= 0:
        return Decimal(0)
    return realized_pnl_usd / margin_used_usd * 100
