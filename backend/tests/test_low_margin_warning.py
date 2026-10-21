"""Pure unit tests, no database."""

from decimal import Decimal

from app.papers.models import Paper
from app.risk_engine.service import _low_margin_warning


def _paper() -> Paper:
    # $100 dip adds.
    return Paper(
        id=7,
        asset="BTC",
        mode="demo",
        kind="averaging",
        initial_size_usd=Decimal(100),
        add_size_usd=Decimal(100),
        add_leverage=Decimal(3),
        leverage=Decimal(10),
    )


def _warn(locked: int | None, cap: int | None, cash: int) -> str | None:
    """The warning for a $100 add with `locked` margin already in."""
    return _low_margin_warning(
        _paper(),
        Decimal(100),
        None if locked is None else Decimal(locked),
        None if cap is None else Decimal(cap),
        Decimal(cash),
    )


def test_warned_at_the_add_leaving_room_for_one_more() -> None:
    # $1,000 max: $800 locked + this $100 add = $900 - $100 left, one add.
    warning = _warn(800, 1000, 5000)
    assert warning is not None
    assert "1 more add left before its max margin" in warning
    assert "margin $900.00 of $1000.00" in warning


def test_not_warned_with_room_for_more_or_once_already_past_it() -> None:
    # $700 locked + $100: $200 left, two adds.
    assert _warn(700, 1000, 5000) is None
    # $900 locked + $100: none left - but the add before already warned.
    assert _warn(900, 1000, 5000) is None


def test_the_free_balance_counts_too_without_a_max_margin() -> None:
    warning = _warn(None, None, 150)
    assert warning is not None
    assert "1 more add left before the free balance" in warning
