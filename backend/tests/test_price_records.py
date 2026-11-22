"""An asset's price records - pure, no database."""

from datetime import date
from decimal import Decimal

from app.market_data.records import Before, Record, broken, message

WINDOWS = [
    Before("its stored history", Decimal(130), Decimal(60)),
    Before("a year", Decimal(120), Decimal(70)),
    Before("half a year", Decimal(110), Decimal(80)),
]


def test_the_widest_window_broken_is_told() -> None:
    assert broken(Decimal(125), Decimal(100), WINDOWS) == Record(
        "high", "a year", Decimal(125), Decimal(120)
    )
    assert broken(Decimal(131), Decimal(100), WINDOWS) == Record(
        "high", "its stored history", Decimal(131), Decimal(130)
    )
    assert broken(Decimal(100), Decimal(75), WINDOWS) == Record(
        "low", "half a year", Decimal(75), Decimal(80)
    )
    assert broken(Decimal(105), Decimal(90), WINDOWS) is None  # inside every range


def test_the_message() -> None:
    record = Record("high", "its stored history", Decimal("128400"), Decimal("126100.5"))
    assert message("BTC", record, date(2025, 10, 12)) == (
        "📈 BTC at its highest price in its stored history (since 2025-10-12): "
        "128,400.00 (before: 126,100.50)"
    )
    low = Record("low", "half a year", Decimal("1500"), Decimal("1520"))
    assert message("ETH", low, None) == (
        "📉 ETH at its lowest price in half a year: 1,500.00 (before: 1,520.00)"
    )
