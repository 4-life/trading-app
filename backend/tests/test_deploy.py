"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta

from app.system.deploy import MAX_SECONDS, SETTLE_SECONDS, Deploy

T0 = datetime(2026, 10, 3, tzinfo=UTC)


def test_quiet_while_running_then_settling_after_the_finish() -> None:
    running = Deploy(T0, None)
    assert running.quiet(T0 + timedelta(minutes=5)) and not running.due(T0 + timedelta(minutes=5))
    done = Deploy(T0, T0 + timedelta(minutes=3))
    assert done.quiet(T0 + timedelta(minutes=3, seconds=SETTLE_SECONDS - 1))
    assert done.due(T0 + timedelta(minutes=3, seconds=SETTLE_SECONDS))


def test_a_deploy_that_never_finishes_stops_the_quiet() -> None:
    stuck = Deploy(T0, None)
    assert stuck.due(T0 + timedelta(seconds=MAX_SECONDS))
