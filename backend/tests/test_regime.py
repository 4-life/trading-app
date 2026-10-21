"""Pure unit tests, no database."""

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.backtest.bars import Bar
from app.backtest.regime import MAX_UNITS, PYRAMID_ADD, pyramid_add, pyramid_stop, simulate
from app.executors.regime import (
    BOTTOM_EXIT,
    DISASTER_EXIT,
    DISASTER_STOP,
    FALSE_BOTTOM_EXIT,
    HH_REJECTION_EXIT,
    LL_REBUY,
    REGIME_EXIT,
    REVERSAL_ENTRY,
    TOP_EXIT,
    View,
    disaster_stop,
    exit_reason,
    held_stop,
    higher_swings,
    rebuy_level,
    reversal_stop,
    trend_signal,
)
from app.executors.swings import Swing, find_swings
from app.executors.trend_bands import Bands

T0 = datetime(2026, 10, 1, tzinfo=UTC)
# (high, low, close).
CANDLES = [
    (100.5, 99.5, 100.0),
    (102.0, 99.8, 101.5),
    (102.5, 101.0, 102.0),
    (101.8, 100.0, 100.8),
    (103.0, 100.5, 102.5),
    (103.5, 102.0, 103.0),
]
N = len(CANDLES)


def _view(
    candles: list[tuple[float, float, float]] = CANDLES,
    state: tuple[int, ...] = (0, 1, 1, 1, 1, 1),
    break_up_at: int | None = None,
    swings: tuple[Swing, ...] = (),
) -> View:
    bands = Bands(
        upper=[110.0] * N,
        lower=[90.0] * N,
        atr=[2.0] * N,
        state=list(state),
        break_up=[k == break_up_at for k in range(N)],
        break_dn=[False] * N,
    )
    highs, lows, closes = (list(x) for x in zip(*candles, strict=True))
    return View("long", 1, highs, lows, closes, bands, list(swings))


def _walk(count: int = 3000) -> list[Bar]:
    """Trending legs up and down with noise."""
    rng = random.Random(7)
    bars, price = [], 100.0
    for k in range(count):
        drift = 0.002 if (k // 700) % 2 == 0 else -0.002
        o, price = price, price * (1 + drift + rng.gauss(0, 0.008))
        h = max(o, price) * (1 + abs(rng.gauss(0, 0.003)))
        low = min(o, price) * (1 - abs(rng.gauss(0, 0.003)))
        bars.append(Bar(T0 + timedelta(hours=k), o, h, low, price, rng.uniform(50, 150)))
    return bars


def test_trend_signal_on_a_flip_or_a_break_up_while_bullish() -> None:
    assert [trend_signal(_view(), k) for k in range(N)] == [False, True] + [False] * 4
    v = _view(state=(1,) * N, break_up_at=3)
    assert [trend_signal(v, k) for k in range(N)] == [False] * 3 + [True, False, False]


# CANDLES: highs 100.5 102 102.5 101.8 103 103.5,
# closes 100 101.5 102 100.8 102.5 103.
HH_AT_2 = Swing("HH", 102.6, 0, 2)  # confirmed on candle 2


def test_disaster_stop_mirrors_for_a_short() -> None:
    assert disaster_stop(100.0) == pytest.approx(100.0 * (1 - DISASTER_STOP))
    assert -disaster_stop(-100.0) == pytest.approx(100.0 * (1 + DISASTER_STOP))


def test_higher_swings_come_from_complete_utc_4h_candles() -> None:
    # The walk starts at 00:00 UTC; without its first hour the first 4h candle
    # is incomplete, so the complete ones start at index 3 (04:00).
    bars = _walk()[1:]
    times, highs, lows = [b.time for b in bars], [b.high for b in bars], [b.low for b in bars]
    groups = [(a, a + 3) for a in range(3, len(bars) - 3, 4)]
    expected = [
        Swing(s.kind, s.price, groups[s.pivot_index][0], groups[s.confirm_index][1])
        for s in find_swings(
            [max(highs[a : b + 1]) for a, b in groups], [min(lows[a : b + 1]) for a, b in groups]
        )
    ]
    assert expected
    assert higher_swings(times, highs, lows, "1h") == expected
    assert higher_swings(times, highs, lows, "4h") == find_swings(highs, lows)


def test_a_reversal_long_keeps_its_tight_stop_until_the_bands_turn_bullish() -> None:
    bearish = _view(state=(-1,) * N)
    assert held_stop(bearish, 98.0, 100.0, True, 1, 4) == (98.0, FALSE_BOTTOM_EXIT)
    stop, reason = held_stop(_view(state=(-1, -1, 1, 1, 1, 1)), 98.0, 100.0, True, 1, 4)
    assert stop == pytest.approx(disaster_stop(100.0))
    assert reason == DISASTER_EXIT
    assert held_stop(bearish, 90.0, 100.0, False, 1, 4)[1] == DISASTER_EXIT


def test_exit_when_the_regime_leaves_bullish_after_the_entry() -> None:
    assert exit_reason(_view(state=(1,) * N), [], 1, N - 1) is None
    assert exit_reason(_view(state=(1, 1, 1, 1, 1, -1)), [], 1, N - 1) == REGIME_EXIT
    # A reversal long while the bands stay bearish: no regime exit.
    assert exit_reason(_view(state=(-1,) * N), [], 1, N - 1) is None


def test_a_short_closes_at_the_bottom_on_an_hh_since_its_entry() -> None:
    # A short's view: an LL there is an HH in real prices.
    ll = (Swing("LL", 99.0, 2, 4),)
    short = replace(_view(state=(1,) * N, swings=ll), direction="short", sign=-1)
    assert exit_reason(short, [], 1, 3) is None
    assert exit_reason(short, [], 1, 4) == BOTTOM_EXIT
    assert exit_reason(short, [], 4, 5) is None  # confirmed by the entry candle


def test_a_long_closes_on_a_rejection_at_the_last_4h_hh() -> None:
    v = _view(state=(1,) * N)
    # Candle 4 reaches 102.6 (high 103) and closes under it (102.5).
    assert exit_reason(v, [HH_AT_2], 1, 4) == HH_REJECTION_EXIT
    assert exit_reason(v, [HH_AT_2], 1, 5) is None  # closes above it (103)
    assert exit_reason(v, [HH_AT_2], 2, 4) is None  # confirmed by the entry candle
    assert exit_reason(v, [replace(HH_AT_2, price=103.2)], 1, 4) is None  # not reached


def test_a_long_closes_on_a_4h_ll_since_its_entry() -> None:
    ll = [Swing("LL", 99.0, 1, 4)]
    assert exit_reason(_view(state=(1,) * N), ll, 1, 3) is None
    assert exit_reason(_view(state=(1,) * N), ll, 1, 4) == TOP_EXIT
    assert exit_reason(_view(state=(1,) * N), ll, 4, 5) is None  # confirmed by the entry candle
    # A reversal long before the bands turned bullish: a false bottom.
    assert exit_reason(_view(state=(-1,) * N), ll, 1, 4, reversal=True) == FALSE_BOTTOM_EXIT
    assert exit_reason(_view(state=(-1, 1, 1, 1, 1, 1)), ll, 1, 4, reversal=True) == TOP_EXIT


def test_reversal_stop_under_the_selloff_low_capped_by_the_disaster_stop() -> None:
    # CANDLES' lows 99.5 99.8 101 100 100.5 102: the lowest since candle 1 is 99.8.
    v = _view()
    assert reversal_stop(v, 1, 4, 102.5) == 99.8
    assert reversal_stop(v, 1, 4, 120.0) == pytest.approx(disaster_stop(120.0))


def test_rebuy_at_a_4h_ll_confirmed_on_the_candle_below_the_close() -> None:
    v = _view(state=(-1,) * N)
    ll = Swing("LL", 101.0, 1, 4)  # candle 4 closes at 102.5
    assert rebuy_level(v, [ll], 4) == 100.0  # half an ATR (2) under the LL
    assert rebuy_level(v, [ll], 5) is None  # confirmed earlier
    assert rebuy_level(v, [replace(ll, price=102.6)], 4) is None  # the close under it
    assert rebuy_level(_view(state=(1,) * N), [ll], 4) is None  # bands bullish


def test_a_bottom_exit_reverses_into_a_long_on_the_same_candle() -> None:
    # Positions only: pyramid adds overlap their position by design.
    simulated = simulate(_walk(), "1h", ("long", "short"))
    trades = [t for t in simulated if t.entry_reason != PYRAMID_ADD]
    pairs = list(zip(trades, trades[1:], strict=False))
    bottoms = [(a, b) for a, b in pairs if a.exit_reason == BOTTOM_EXIT]
    assert bottoms
    for a, b in bottoms:
        assert (b.direction, b.entry_reason, b.opened_at) == ("long", REVERSAL_ENTRY, a.closed_at)
    for a, b in pairs:
        assert a.closed_at is not None and b.opened_at >= a.closed_at


def test_after_a_false_bottom_the_next_trade_is_a_long() -> None:
    trades = simulate(_walk(), "1h", ("long", "short"))
    assert any(t.exit_reason == FALSE_BOTTOM_EXIT for t in trades)
    for a, b in zip(trades, trades[1:], strict=False):
        if a.exit_reason == FALSE_BOTTOM_EXIT:
            assert b.direction == "long"
    for t in trades:
        if t.entry_reason == LL_REBUY:
            assert t.stop_loss_price is not None and t.stop_loss_price < t.entry_price


def test_pyramid_adds_on_a_close_above_a_4h_hh_confirmed_since_the_entry() -> None:
    hh = Swing("HH", 102.0, 0, 3)  # confirmed on candle 3; candle 4 closes at 102.5
    up = _view(state=(1,) * N)
    assert pyramid_add(up, [hh], 1, 4) == hh
    assert pyramid_add(up, [hh], 1, 3) is None  # not on its own confirmation
    assert pyramid_add(up, [hh], 3, 4) is None  # confirmed by the entry candle
    assert pyramid_add(up, [replace(hh, price=102.6)], 1, 4) is None  # closes under it
    assert pyramid_add(_view(state=(-1,) * N), [hh], 1, 4) is None  # bands not bullish


def test_pyramid_stop_moves_under_the_last_4h_hl_never_down() -> None:
    hls = [Swing("HL", 99.0, 1, 2), Swing("HL", 98.0, 3, 4)]
    assert pyramid_stop(hls, 1, None) is None  # none confirmed yet
    assert pyramid_stop(hls, 3, None) == 99.0
    assert pyramid_stop(hls, 4, 99.0) == 99.0  # the lower HL doesn't move it down


def test_pyramid_units_close_together() -> None:
    trades = simulate(_walk(), "1h", ("long",))
    adds = [t for t in trades if t.entry_reason == PYRAMID_ADD]
    assert adds
    for unit in adds:
        first = next(
            t
            for t in trades
            if t.entry_reason != PYRAMID_ADD
            and t.opened_at < unit.opened_at
            and t.closed_at == unit.closed_at
        )
        assert first.exit_reason == unit.exit_reason and first.close_price == unit.close_price
    by_close: dict[object, int] = {}
    for t in trades:
        by_close[t.closed_at] = by_close.get(t.closed_at, 0) + 1
    assert max(by_close.values()) <= MAX_UNITS
