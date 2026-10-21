"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.execution_engine.demo import (
    Quote,
    close_fill,
    fill_price,
    funding_paid,
    open_fill,
)
from app.system.exchange_api import TAKER_FEE_RATES

T0 = datetime(2026, 1, 1, tzinfo=UTC)
FEE = TAKER_FEE_RATES["hyperliquid"]


def _at(price: int) -> Quote:
    return Quote(Decimal(price), Decimal(price))


def test_fill_price_crosses_the_spread() -> None:
    quote = Quote(bid=Decimal("99.9"), ask=Decimal("100.1"))
    assert fill_price(quote, "buy") == Decimal("100.1")
    assert fill_price(quote, "sell") == Decimal("99.9")
    assert quote.mid == Decimal(100)


def test_open_fill_reserves_notional_over_leverage() -> None:
    fill = open_fill("long", Decimal(3000), Decimal(3), _at(100), FEE)
    assert fill.margin_usd == Decimal(1000)
    assert fill.fee_usd == Decimal(3000) * FEE
    assert fill.size * fill.price == Decimal(3000)


def test_close_fill_pnl_by_direction() -> None:
    size, entry = Decimal(10), Decimal(100)
    long_close = close_fill("long", size, entry, _at(110), Decimal(0), FEE)
    short_close = close_fill("short", size, entry, _at(110), Decimal(0), FEE)
    assert long_close.settlement_pnl_usd > 0
    assert short_close.settlement_pnl_usd < 0
    gross_long = (long_close.price - entry) * size
    assert long_close.settlement_pnl_usd == gross_long - long_close.fee_usd


def test_lighter_charges_no_fee() -> None:
    fee = TAKER_FEE_RATES["lighter"]
    assert open_fill("long", Decimal(3000), Decimal(3), _at(100), fee).fee_usd == 0
    close = close_fill("long", Decimal(10), Decimal(100), _at(110), Decimal(0), fee)
    assert close.fee_usd == 0
    assert close.settlement_pnl_usd == Decimal(100)


def test_funding_only_counts_rates_while_open() -> None:
    rates = [
        (T0 - timedelta(hours=1), Decimal("0.01")),  # before open
        (T0 + timedelta(hours=1), Decimal("0.001")),
        (T0 + timedelta(hours=2), Decimal("0.002")),
        (T0 + timedelta(hours=5), Decimal("0.01")),  # after close
    ]
    closed = T0 + timedelta(hours=3)
    long_paid = funding_paid("long", Decimal(1), Decimal(100), rates, T0, closed)
    short_paid = funding_paid("short", Decimal(1), Decimal(100), rates, T0, closed)
    assert long_paid == Decimal("0.3")
    assert short_paid == Decimal("-0.3")
