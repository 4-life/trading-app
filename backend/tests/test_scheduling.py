"""Pure unit tests, no database."""

from unittest import mock

import app.scheduling as scheduling


async def _slept(now: float, period: float, offset: float) -> float:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    with (
        mock.patch("app.scheduling.asyncio.sleep", fake_sleep),
        mock.patch("app.scheduling.time.time", lambda: now),
    ):
        await scheduling.sleep_until_next(period, offset)
    return slept[0]


async def test_sleeps_until_the_next_offset_in_the_same_minute() -> None:
    assert await _slept(60_000 + 3.0, 60, 5) == 2.0


async def test_sleeps_until_the_next_minute_once_the_offset_passed() -> None:
    assert await _slept(60_000 + 30.0, 60, 5) == 35.0


async def test_exactly_on_the_offset_waits_a_full_period() -> None:
    assert await _slept(60_000 + 5.0, 60, 5) == 60.0
