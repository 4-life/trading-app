"""A closed position's lasting record (app/execution_engine/models.py)."""

from datetime import UTC, datetime
from decimal import Decimal

from app.execution_engine.models import ClosedPosition, Position

T0 = datetime(2026, 11, 1, tzinfo=UTC)
T1 = datetime(2026, 11, 2, tzinfo=UTC)


def test_record_keeps_the_whole_margin_and_the_position_id() -> None:
    position = Position(
        id=7,
        paper_id=3,
        mode="live",
        asset="BTC",
        direction="long",
        size=Decimal(1),
        entry_price=Decimal(100),
        margin_usd=Decimal(5),
        initial_margin_usd=Decimal(20),
        opened_at=T0,
        closed_at=T1,
        exit_reason="sell",
    )
    record = ClosedPosition.of(position, Decimal(110), Decimal(12))
    assert (record.position_id, record.paper_id, record.mode) == (7, 3, "live")
    assert record.margin_usd == Decimal(20)
    assert (record.close_price, record.realized_pnl_usd) == (Decimal(110), Decimal(12))
    assert (record.opened_at, record.closed_at, record.exit_reason) == (T0, T1, "sell")


def test_record_has_no_foreign_key_to_the_paper() -> None:
    assert not ClosedPosition.__table__.foreign_keys
