"""Pure unit tests, no database or network."""

from decimal import Decimal

import pytest

from app.execution_engine.live import LiveOrderError, parse_order_response, round_size


def _response(status: dict[str, object]) -> dict[str, object]:
    return {"status": "ok", "response": {"type": "order", "data": {"statuses": [status]}}}


def test_filled_order() -> None:
    fill = parse_order_response(
        _response({"filled": {"totalSz": "0.012", "avgPx": "83421.5", "oid": 77738308}})
    )
    assert fill.order_id == 77738308
    assert fill.price == Decimal("83421.5")
    assert fill.size == Decimal("0.012")


def test_unfilled_ioc_order_is_an_error() -> None:
    with pytest.raises(LiveOrderError, match="could not immediately match"):
        parse_order_response(
            _response({"error": "Order could not immediately match against any resting orders."})
        )


def test_rejected_request_is_an_error() -> None:
    with pytest.raises(LiveOrderError):
        parse_order_response({"status": "err", "response": "User or API Wallet does not exist."})


def test_resting_order_is_not_a_fill() -> None:
    with pytest.raises(LiveOrderError, match="not filled"):
        parse_order_response(_response({"resting": {"oid": 1}}))


def test_round_size_rounds_down_to_the_size_step() -> None:
    assert round_size(Decimal("0.0119849"), 5) == Decimal("0.01198")
    assert round_size(Decimal("3.99"), 0) == Decimal("3")
