"""Pure unit tests, no database: the store and the provider are stubbed."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.market_data import collector

HOUR = 3_600_000
START, END = 0, 1000 * HOUR


def _run(
    monkeypatch: pytest.MonkeyPatch,
    missing: list[tuple[int, int]],
    history_start: int | None,
    returns: dict[int, tuple[int, int | None]],
) -> tuple[list[tuple[int, int]], dict[str, int]]:
    """backfill_candles over [START, END] at 1h: the ranges it requested and
    the history start it saved."""
    requested: list[tuple[int, int]] = []
    saved: dict[str, int] = {}

    async def source() -> Any:
        return SimpleNamespace(provider="lighter")

    async def missing_ranges(*_: Any) -> list[tuple[int, int]]:
        return missing

    async def stored(_: str) -> int | None:
        return history_start

    async def save(key: str, start_ms: int) -> None:
        saved[key] = start_ms

    async def fetch(_a: Any, _s: str, _i: str, start: int, end: int) -> tuple[int, int | None]:
        requested.append((start, end))
        return returns.get(start, (0, None))

    monkeypatch.setattr(collector, "data_source", source)
    monkeypatch.setattr(collector, "_missing_candle_ranges", missing_ranges)
    monkeypatch.setattr(collector, "_history_start", stored)
    monkeypatch.setattr(collector, "_save_history_start", save)
    monkeypatch.setattr(collector, "_fetch_candle_range", fetch)
    asyncio.run(collector.backfill_candles(None, "SOXL", "1h", START, END))  # type: ignore[arg-type]
    return requested, saved


def test_an_empty_range_before_the_first_stored_candle_is_remembered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Stored from hour 600: nothing came back before it.
    requested, saved = _run(monkeypatch, [(START, 600 * HOUR)], None, {})
    assert requested == [(START, 600 * HOUR)]
    assert saved == {"candle_history_start:lighter:SOXL:1h": 600 * HOUR}


def test_a_first_backfill_remembers_where_the_returned_history_begins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, saved = _run(monkeypatch, [(START, END)], None, {START: (400, 600 * HOUR)})
    assert saved == {"candle_history_start:lighter:SOXL:1h": 600 * HOUR}


def test_the_range_before_the_history_start_is_never_requested_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The head before hour 600 skipped, a later gap still filled.
    missing = [(START, 600 * HOUR), (800 * HOUR, 810 * HOUR)]
    requested, saved = _run(monkeypatch, missing, 600 * HOUR, {})
    assert requested == [(800 * HOUR, 810 * HOUR)]
    assert saved == {}


def test_a_history_reaching_the_range_start_saves_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _, saved = _run(monkeypatch, [(START, END)], None, {START: (1000, START)})
    assert saved == {}


def _t(hour: int) -> datetime:
    return collector._ms_to_utc(hour * HOUR)


def test_funding_from_shortly_after_the_range_start_covers_it() -> None:
    # The provider's first row ~17h after the start (Lighter, a year's range).
    covered = collector.funding_covered
    assert covered(_t(17), _t(1000), _t(0), _t(1000), timedelta(hours=1), None)
    assert not covered(_t(30), _t(1000), _t(0), _t(1000), timedelta(hours=1), None)
    assert not covered(_t(17), _t(998), _t(0), _t(1000), timedelta(hours=1), None)


def test_funding_from_its_history_start_covers_a_range_reaching_before_it() -> None:
    covered = collector.funding_covered
    assert covered(_t(600), _t(1000), _t(0), _t(1000), timedelta(hours=1), _t(600))
    assert not covered(_t(700), _t(1000), _t(0), _t(1000), timedelta(hours=1), _t(600))


def _run_funding(
    monkeypatch: pytest.MonkeyPatch, earliest_hour: int | None, first_row_hour: int
) -> dict[str, int]:
    """backfill_funding over [START, END], the store holding rows from
    `earliest_hour` to hour 900, the provider returning from `first_row_hour`:
    the history start it saved."""
    saved: dict[str, int] = {}

    async def source() -> Any:
        return SimpleNamespace(provider="lighter")

    async def stored(_: str) -> int | None:
        return None

    async def save(key: str, start_ms: int) -> None:
        saved[key] = start_ms

    async def bounds(_: str) -> tuple[datetime | None, datetime | None]:
        return (None, None) if earliest_hour is None else (_t(earliest_hour), _t(900))

    class Adapter:
        async def get_funding_history(self, *_: Any) -> list[dict[str, Any]]:
            return [{"time": first_row_hour * HOUR, "fundingRate": "0", "premium": "0"}]

    class Session:
        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def execute(self, _: Any) -> None:
            return None

        async def commit(self) -> None:
            return None

    monkeypatch.setattr(collector, "data_source", source)
    monkeypatch.setattr(collector, "_history_start", stored)
    monkeypatch.setattr(collector, "_save_history_start", save)
    monkeypatch.setattr(collector, "_funding_bounds", bounds)
    monkeypatch.setattr(collector, "async_session", Session)
    asyncio.run(collector.backfill_funding(Adapter(), "SOXL", START, END))  # type: ignore[arg-type]
    return saved


def test_a_funding_backfill_remembers_where_the_providers_history_begins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = _run_funding(monkeypatch, None, 600)
    assert saved == {"funding_history_start:lighter:SOXL": 600 * HOUR}
    # Before the stored rows again: the same.
    assert _run_funding(monkeypatch, 650, 600) == {"funding_history_start:lighter:SOXL": 600 * HOUR}


def test_a_live_funding_poll_saves_no_history_start(monkeypatch: pytest.MonkeyPatch) -> None:
    # The stored rows begin before the range: a poll for the latest rows.
    assert _run_funding(monkeypatch, -10, 600) == {}
