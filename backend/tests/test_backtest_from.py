"""Where a backtest and a sweep start (app/backtest/bars.py find_backtest_from)."""

from datetime import UTC, datetime, timedelta

from app.backtest.bars import MIN_TESTED, BacktestFrom, Bar, find_backtest_from

T0 = datetime(2026, 1, 1, tzinfo=UTC)
DAY = timedelta(days=1)


def _bar(day: int, low: float, high: float, close: float | None = None) -> Bar:
    close = (low + high) / 2 if close is None else close
    return Bar(T0 + DAY * day, close, high, low, close)


def _days(*lows: float) -> list[Bar]:
    """A candle per day, 1 wide, from each low."""
    return [_bar(k, low, low + 1) for k, low in enumerate(lows)]


def test_earliest_candle_holding_the_current_price() -> None:
    bars = [*_days(50, 60, 70, 70, 80), *(_bar(k, 60, 80) for k in range(5, 60)), _bar(60, 70, 71)]
    assert find_backtest_from(bars, None) == BacktestFrom(bars[2].time, bars[-1].close)


def test_a_wick_through_the_price_counts() -> None:
    bars = [_bar(0, 50, 51), _bar(1, 50, 90, 51), *(_bar(k, 50, 51) for k in range(2, 40))]
    bars[-1] = _bar(39, 69, 71, 70)
    assert find_backtest_from(bars, None) == BacktestFrom(bars[1].time, 70)


def test_a_new_high_tests_the_whole_history() -> None:
    bars = _days(*(float(k) * 10 for k in range(60)))
    assert find_backtest_from(bars, None) == BacktestFrom(bars[0].time, None)


def test_reached_too_recently_tests_the_whole_history() -> None:
    days = MIN_TESTED.days
    bars = [*(_bar(k, 10, 11) for k in range(40)), *(_bar(40 + k, 90, 91) for k in range(days))]
    assert find_backtest_from(bars, None) == BacktestFrom(bars[0].time, None)


def test_reached_just_long_enough_ago_starts_there() -> None:
    days = MIN_TESTED.days
    bars = [*(_bar(k, 10, 11) for k in range(40)), *(_bar(40 + k, 90, 91) for k in range(days + 1))]
    assert find_backtest_from(bars, None) == BacktestFrom(bars[40].time, bars[-1].close)


def test_a_set_date_wins() -> None:
    manual = T0 + DAY * 3
    assert find_backtest_from(_days(50, 60), manual) == BacktestFrom(manual, None)


def test_no_candles() -> None:
    assert find_backtest_from([], None) == BacktestFrom(None, None)
