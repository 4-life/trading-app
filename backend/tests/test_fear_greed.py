"""The Fear & Greed index - pure, no network."""

import time
from datetime import UTC, datetime

import pytest

from app.sentiment import fear_greed
from app.sentiment.alternative_me import parse
from app.sentiment.fear_greed import FearGreed, latest_fear_greed


def test_the_answer_is_parsed() -> None:
    latest = {"value": "23", "value_classification": "Extreme Fear", "timestamp": "1763769600"}
    body = {"data": [latest]}
    assert parse(body) == FearGreed(23, "Extreme Fear", datetime(2025, 11, 22, tzinfo=UTC))
    with pytest.raises(ValueError):
        parse({"data": []})


class _Source:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    async def latest(self) -> FearGreed:
        self.calls += 1
        if self.fail:
            raise OSError("down")
        return FearGreed(40 + self.calls, "Fear", datetime(2026, 11, 22, tzinfo=UTC))


class _Store:
    def __init__(self, kept: FearGreed | None = None) -> None:
        self.kept = kept

    async def save(self, reading: FearGreed) -> None:
        self.kept = reading

    async def load(self) -> FearGreed | None:
        return self.kept


async def test_it_is_read_once_an_hour_and_the_last_value_kept_through_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(fear_greed, "_cached", None)
    source, store = _Source(), _Store()
    first = await latest_fear_greed(source, store)
    assert first is not None and first.value == 41 and store.kept == first
    clock[0] += 60
    assert await latest_fear_greed(source, store) == first and source.calls == 1
    clock[0] += fear_greed.REFRESH_SECONDS
    source.fail = True
    stale = await latest_fear_greed(source, store)
    assert stale is not None and (stale.value, stale.stale) == (41, True)
    assert await latest_fear_greed(source, store) == stale and source.calls == 2  # retried later
    clock[0] += fear_greed.RETRY_SECONDS
    source.fail = False
    fresh = await latest_fear_greed(source, store)
    assert fresh is not None and (fresh.value, fresh.stale) == (43, False)


async def test_after_a_restart_the_stored_value_shows_while_the_source_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fear_greed, "_cached", None)
    source = _Source()
    source.fail = True
    kept = FearGreed(23, "Extreme Fear", datetime(2026, 11, 21, tzinfo=UTC))
    reading = await latest_fear_greed(source, _Store(kept))
    assert reading is not None and (reading.value, reading.stale) == (23, True)
