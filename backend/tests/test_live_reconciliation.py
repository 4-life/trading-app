"""Pure unit tests, no database or exchange."""

from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.watchdog import checks

Row = tuple[str, str, Decimal]


class _Session:
    def __init__(self, rows: list[Row]) -> None:
        self.rows = rows

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, _statement: Any) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: self.rows)


class _World:
    """What the check sees: the exchange account and the database's live positions."""

    def __init__(self) -> None:
        self.exchange: dict[str, Decimal] = {}
        self.rows: list[Row] = []

    async def client(self) -> _World:
        return self

    async def positions(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(asset=a, size=s) for a, s in self.exchange.items()]


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[_World]:
    w = _World()
    monkeypatch.setattr(checks, "live_client", w.client)
    monkeypatch.setattr(checks, "async_session", lambda: _Session(w.rows))
    # Start past the first pass: most tests are about a running watchdog.
    monkeypatch.setattr(checks, "_unconfirmed_mismatches", set())
    yield w


async def test_order_in_flight_does_not_fail_and_clears_once_recorded(world: _World) -> None:
    world.exchange = {"AAA": Decimal("10.40")}
    first = await checks.check_live_reconciliation()
    assert first.ok
    assert "AAA: app 0 vs exchange 10.40" in first.detail

    world.rows = [("AAA", "long", Decimal("10.40"))]
    second = await checks.check_live_reconciliation()
    assert second.ok
    assert second.detail == "1 live position(s) match"


async def test_mismatch_on_two_passes_in_a_row_fails(world: _World) -> None:
    world.exchange = {"AAA": Decimal("10.40")}
    assert (await checks.check_live_reconciliation()).ok

    second = await checks.check_live_reconciliation()
    assert not second.ok
    assert second.detail == "AAA: app 0 vs exchange 10.40"


async def test_only_the_repeated_asset_fails(world: _World) -> None:
    world.exchange = {"AAA": Decimal("10.40")}
    await checks.check_live_reconciliation()

    world.exchange = {"AAA": Decimal("10.40"), "BBB": Decimal(1)}
    result = await checks.check_live_reconciliation()
    assert not result.ok
    assert result.detail == "AAA: app 0 vs exchange 10.40"


async def test_first_pass_after_startup_has_no_grace(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checks, "_unconfirmed_mismatches", None)
    world.exchange = {"AAA": Decimal("10.40")}
    assert not (await checks.check_live_reconciliation()).ok


async def test_short_position_matches_negative_exchange_size(world: _World) -> None:
    world.exchange = {"CCC": Decimal(-2)}
    world.rows = [("CCC", "short", Decimal(2))]
    assert (await checks.check_live_reconciliation()).ok
