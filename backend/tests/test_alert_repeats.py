"""Repeated alerts and a close to a position the exchange no longer holds -
pure, no database."""

import time
from decimal import Decimal

import pytest

from app.execution_engine.engine import held_on_exchange
from app.watchdog import engine


def test_a_position_is_held_on_the_exchange_by_its_signed_size() -> None:
    assert held_on_exchange("long", Decimal("0.5"))
    assert held_on_exchange("short", Decimal("-3.4935"))
    assert not held_on_exchange("short", Decimal(0))  # liquidated there
    assert not held_on_exchange("long", Decimal("-1"))  # the other way


async def test_a_failing_check_alerts_again_only_on_a_change_or_after_a_while(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []

    async def fake_alert(source: str, level: str, message: str) -> None:
        sent.append(message)

    clock = [1000.0]
    monkeypatch.setattr(engine, "alert", fake_alert)
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(engine, "_last_sent", {})
    await engine._alert_on_change("critical", "ETH mismatch")
    await engine._alert_on_change("critical", "ETH mismatch")  # a minute on: quiet
    assert sent == ["ETH mismatch"]
    await engine._alert_on_change("critical", "ETH and BTC mismatch")  # changed
    clock[0] += engine.REPEAT_SECONDS
    await engine._alert_on_change("critical", "ETH and BTC mismatch")  # half an hour on
    assert sent == ["ETH mismatch", "ETH and BTC mismatch", "ETH and BTC mismatch"]
