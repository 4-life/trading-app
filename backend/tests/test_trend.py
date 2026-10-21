"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.executors.trend import (
    BREAKOUT_LONG,
    BREAKOUT_SHORT,
    TRAILING_STOP,
    Bar,
    Held,
    atr,
    bars_for_days,
    bear_market,
    decide_signal,
    stop_loss_hit,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(hours=4)


def _bars(closes: list[float], spread: float = 1.0) -> list[Bar]:
    return [Bar(T0 + i * STEP, c + spread, c - spread, c, 1.0) for i, c in enumerate(closes)]


def _breakout(
    close: float, *, direction: str = "long", volume: float = 3.0, wick: float = 0.0
) -> list[Bar]:
    """20 flat candles at 100 (volume 1), then a 2-wide breakout candle closing
    at `close` - at its high (long) / low (short), less `wick`."""
    t = T0 + 20 * STEP
    if direction == "long":
        last = Bar(t, close + wick, close - 2, close, volume)
    else:
        last = Bar(t, close + 2, close - wick, close, volume)
    return [*_bars([100.0] * 20), last]


def test_bars_for_days() -> None:
    assert bars_for_days(20, "4h") == 120
    assert bars_for_days(200, "4h") == 1200
    assert bars_for_days(20, "1h") == 480


def test_atr_of_a_steady_range() -> None:
    assert atr(_bars([100.0] * 50)) == pytest.approx(2.0)


def test_bear_market_needs_full_history() -> None:
    assert bear_market([100.0] * 9, 10) is None
    assert bear_market([110.0] * 9 + [100.0], 10) is True
    assert bear_market([90.0] * 9 + [100.0], 10) is False


def test_close_above_the_breakout_high_opens_long_with_initial_stop() -> None:
    signal = decide_signal(_breakout(105.0), 10, None, bear=None)
    assert signal is not None and (signal.signal, signal.direction, signal.reason) == (
        "enter",
        "long",
        BREAKOUT_LONG,
    )
    # the 1% stop is nearer than 3 x ATR here
    assert signal.stop_loss_price == pytest.approx(Decimal("103.95"))
    assert decide_signal(_breakout(100.5), 10, None, bear=None) is None  # below the high 101


def test_short_breakout_only_in_a_bear_market() -> None:
    bars = _breakout(95.0, direction="short")
    assert decide_signal(bars, 10, None, bear=None) is None
    assert decide_signal(bars, 10, None, bear=False) is None
    signal = decide_signal(bars, 10, None, bear=True)
    assert signal is not None and (signal.direction, signal.reason) == ("short", BREAKOUT_SHORT)


def test_long_trails_the_best_price_and_exits_on_a_close_below_it() -> None:
    # Entered at the close of bar 10; best high after it 121; ATR ~3.3 -> stop ~111.
    closes = [100.0] * 10 + [105.0, 110.0, 120.0, 116.0]
    held = Held("long", T0 + 11 * STEP)
    assert decide_signal(_bars(closes), 10, held, bear=None) is None
    signal = decide_signal(_bars([*closes, 105.0]), 10, held, bear=None)
    assert signal is not None and (signal.signal, signal.reason) == ("exit", TRAILING_STOP)


def test_no_exit_before_a_candle_closes_after_entry() -> None:
    held = Held("long", T0 + 100 * STEP)  # after every bar
    assert decide_signal(_bars([100.0] * 10 + [90.0]), 10, held, bear=None) is None


def test_short_trails_the_lowest_price() -> None:
    closes = [100.0] * 10 + [95.0, 88.0, 80.0, 84.0]
    held = Held("short", T0 + 11 * STEP)
    assert decide_signal(_bars(closes), 10, held, bear=True) is None
    signal = decide_signal(_bars([*closes, 95.0]), 10, held, bear=True)  # stop ~89
    assert signal is not None and (signal.direction, signal.reason) == ("short", TRAILING_STOP)


def test_stop_loss_one_percent_from_the_entry() -> None:
    entry = Decimal("100")
    assert not stop_loss_hit("long", entry, Decimal("99.01"))
    assert stop_loss_hit("long", entry, Decimal("99"))
    assert not stop_loss_hit("short", entry, Decimal("100.99"))
    assert stop_loss_hit("short", entry, Decimal("101"))


def test_breakout_needs_double_volume() -> None:
    assert decide_signal(_breakout(105.0, volume=2.0), 10, None, bear=None) is not None
    assert decide_signal(_breakout(105.0, volume=1.9), 10, None, bear=None) is None
    assert (
        decide_signal(_breakout(95.0, direction="short", volume=1.9), 10, None, bear=True) is None
    )


def test_breakout_needs_a_strong_close() -> None:
    # range 103..107 (wick 2): close at 50% of it -> rejected
    assert decide_signal(_breakout(105.0, wick=2.0), 10, None, bear=None) is None
    # range 103..105.5: close at 80% -> confirmed
    assert decide_signal(_breakout(105.0, wick=0.5), 10, None, bear=None) is not None
    assert decide_signal(_breakout(95.0, direction="short", wick=2.0), 10, None, bear=True) is None
