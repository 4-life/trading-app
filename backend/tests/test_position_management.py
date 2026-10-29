"""Pure unit tests, no database."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.papers import PositionManagement, _check_management
from app.execution_engine.demo import grow
from app.executors.base import add_window
from app.executors.position_management import (
    AVERAGE_DOWN,
    MAX_DRAWDOWN_EXIT,
    OUT_OF_MARGIN_EXIT,
    SIGNAL_ADD,
    TAKE_PROFIT_EXIT,
    UNWIND_EXIT,
    add_terms,
    held_units,
    managed_signal,
    margin_levels,
    next_unwind,
    signal_add,
    stops_paper,
    take_profit_close,
    take_profit_sell,
    unwind_buffer,
    unwind_level,
    unwound_unit,
)
from app.order_queue import Direction, Signal
from app.papers.models import Paper

D = Decimal


def _signal(price: str, direction: Direction = "long", dd: str | None = "0.4") -> Signal | None:
    """$10 margin behind a size of 1 (10x at 100), first bought at 100."""
    return managed_signal(
        direction, D(price), D(100), D(1), D(10), D(100), None if dd is None else D(dd)
    )


def _reason(signal: Signal | None) -> tuple[str, str] | None:
    return None if signal is None else (signal.signal, signal.reason)


def test_a_long_adds_once_its_loss_has_taken_half_the_margin() -> None:
    assert _signal("95.5") is None  # $4.50 of the $10 lost: 55% left
    assert _reason(_signal("95")) == ("add", AVERAGE_DOWN)  # 50% left


def test_the_give_up_against_the_first_buy_comes_before_an_add() -> None:
    assert _reason(_signal("60")) == ("exit", MAX_DRAWDOWN_EXIT)
    assert _signal("60", dd=None) == Signal("exit", "long", OUT_OF_MARGIN_EXIT)


def test_with_no_add_the_position_gives_up_before_its_liquidation() -> None:
    # $10 behind a size of 1 at 100: an add was due at 95 (50% left); none
    # came - at 93 (30% left) it closes, before the liquidation at 92 (20%).
    assert _reason(_signal("93.5", dd=None)) == ("add", AVERAGE_DOWN)
    assert _reason(_signal("93", dd=None)) == ("exit", OUT_OF_MARGIN_EXIT)


def test_a_short_is_mirrored() -> None:
    assert _reason(_signal("105", "short")) == ("add", AVERAGE_DOWN)
    assert _signal("104.5", "short") is None
    assert _reason(_signal("140", "short")) == ("exit", MAX_DRAWDOWN_EXIT)


def test_the_take_profit_is_a_floor_on_margin_under_the_strategys_sell() -> None:
    sell = Signal("exit", "long", "hh_rejection")
    # $20 of margin behind a size of 1.3 at an average of 100: 30% of it is $6, at ~104.6.
    assert take_profit_sell(sell, D(105), D(100), D("1.3"), D(20), D(0), D("0.3")) == Signal(
        "exit", "long", f"{TAKE_PROFIT_EXIT}:hh_rejection"
    )
    assert take_profit_sell(sell, D(104), D(100), D("1.3"), D(20), D(0), D("0.3")) is None
    entry = Signal("enter", "long", "x")
    assert take_profit_sell(entry, D(200), D(100), D("1.3"), D(20), D(0), D("0.3")) is None
    short = Signal("exit", "short", "regime_flip")
    assert take_profit_sell(short, D(95), D(100), D("1.3"), D(20), D(0), D("0.3")) is not None


def test_the_take_profit_counts_the_unwinds_realized_pnl() -> None:
    sell = Signal("exit", "long", "hh_rejection")
    # The size held is $6.50 up at 105 - but the unwinds booked -$10: the
    # position is in loss overall, so it waits.
    assert take_profit_sell(sell, D(105), D(100), D("1.3"), D(20), D(-10), D("0.3")) is None
    assert take_profit_sell(sell, D(105), D(100), D("1.3"), D(20), D(1), D("0.3")) is not None


def test_an_add_grows_the_position_and_lowers_its_leverage() -> None:
    # $10 at 10x at 602 ($100), then $10 at 3x at 596 ($30).
    first = D(100) / D(602)
    added = D(30) / D(596)
    g = grow(first, D(602), D(10), added, D(596), D(10))
    assert g.size == first + added
    assert g.entry_price == pytest.approx(D(130) / (first + added))
    assert g.margin_usd == 20
    assert g.leverage == pytest.approx(D("6.5"))


def test_position_management_is_required_on_averaging_papers_only() -> None:
    full = PositionManagement(
        initial_size_usd=D(10),
        add_leverage=D(3),
        take_profit_pct=D("0.3"),
        max_drawdown_pct=D("0.4"),
    )
    _check_management("averaging", full)  # add_size_usd defaults to initial_size_usd
    with pytest.raises(ValidationError):  # adds above 5x can't prevent a margin call
        PositionManagement(add_leverage=D(6))
    _check_management("single", PositionManagement())
    _check_management("scanner", PositionManagement())
    with pytest.raises(HTTPException):
        _check_management("averaging", full.model_copy(update={"take_profit_pct": None}))
    with pytest.raises(HTTPException):
        _check_management("single", full)
    with pytest.raises(HTTPException):
        _check_management("scanner", PositionManagement(take_profit_pct=D("0.3")))
    start = datetime(2026, 3, 15, tzinfo=UTC)  # a backtest start is an averaging setting too
    with pytest.raises(HTTPException):
        _check_management("single", PositionManagement(backtest_start=start))


def test_an_averaging_paper_stops_at_its_take_profit_only() -> None:
    averaging = Paper(kind="averaging", intraday=False)
    assert stops_paper(averaging, f"{TAKE_PROFIT_EXIT}:hh_rejection")
    assert not stops_paper(averaging, MAX_DRAWDOWN_EXIT)
    assert not stops_paper(Paper(kind="single", intraday=False), TAKE_PROFIT_EXIT)
    # An intraday one keeps running.
    assert not stops_paper(Paper(kind="averaging", intraday=True), TAKE_PROFIT_EXIT)


def test_every_strategy_entry_signal_adds_while_a_position_is_open() -> None:
    entry = Signal("enter", "long", "buy_signal")
    assert signal_add(entry, "long") == Signal("add", "long", SIGNAL_ADD)
    assert signal_add(None, "long") is None  # no entry signal
    assert signal_add(Signal("exit", "long", "x"), "long") is None
    assert signal_add(Signal("enter", "short", "x"), "long") is None  # the other direction


def test_every_buy_is_a_unit_and_each_sale_the_lowest_but_the_lowest() -> None:
    fills = [
        ("buy", D(100), D(1)),  # the first buy
        ("buy", D(105), D(1)),  # a signal add above it: a unit too
        ("buy", D(91), D(1)),
        ("buy", D(95), D(1)),
        ("sell", D(100), D(1)),  # took the lowest unit but the lowest (95)
    ]
    assert held_units(1, fills) == [(D(100), D(1)), (D(105), D(1)), (D(91), D(1))]


def test_the_owners_grid() -> None:
    """100 open, 90 signal add, 80 / 70 / 60 dips; back up: 70 sold at 80, 80
    at 90, a 90 signal add, both 90s at 100, then 100 at 120's level once
    the 120 signal add came; 60 kept to the close."""
    buffer = unwind_buffer(D("0.0005"))
    units = [(D(p), D(1)) for p in (100, 90, 80, 70, 60)]
    assert unwind_level(1, units, buffer) == D(80)  # 70 at the next-higher unit
    units.remove((D(70), D(1)))
    assert unwind_level(1, units, buffer) == D(90)  # 80
    units.remove((D(80), D(1)))
    units.append((D(90), D(1)))  # the signal add
    assert unwound_unit(1, units) == (D(90), D(1))
    assert unwind_level(1, units, buffer) == D(100)  # the first 90
    units.remove((D(90), D(1)))
    assert unwind_level(1, units, buffer) == D(100)  # the second 90
    units.remove((D(90), D(1)))
    # 100 is now the highest: half the way from 60 above it.
    assert unwind_level(1, units, buffer) == D(120)
    units.append((D(120), D(1)))  # a signal add
    assert unwind_level(1, units, buffer) == D(120)  # 100 at the next-higher unit
    units.remove((D(100), D(1)))
    assert unwind_level(1, units, buffer) == D(150)  # 120 + (120 - 60) / 2
    units.remove((D(120), D(1)))
    assert unwind_level(1, units, buffer) is None  # 60 is the lowest: kept


def test_a_unit_never_sells_under_its_own_price_plus_the_buffer() -> None:
    buffer = unwind_buffer(D("0.0005"))  # 0.4% markup + 2 x 0.05% fees = 0.5%
    assert buffer == D("0.005")
    # The next-higher unit too close: its own price + the buffer.
    assert unwind_level(1, [(D(100), D(1)), (D("100.1"), D(1)), (D(99), D(1))], buffer) == D(
        "100.500"
    )
    # The highest unit near the lowest: half the gap is under the buffer.
    assert unwind_level(1, [(D(100), D(1)), (D("99.6"), D(1))], buffer) == D("100.500")


def test_the_next_unwind_once_the_price_is_at_its_level() -> None:
    units = [(D(100), D("0.3")), (D(95), D("0.3")), (D(91), D("0.3")), (D(87), D("0.3"))]
    buffer = unwind_buffer(D("0.0005"))
    # 87 kept to the close: 91 sold at 95.
    assert next_unwind("long", D("94.9"), units, D("1.2"), buffer) is None
    sell = next_unwind("long", D(95), units, D("1.2"), buffer)
    assert sell == Signal("exit", "long", UNWIND_EXIT, close_fraction=D("0.3") / D("1.2"))
    # A single unit is the lowest: never sold.
    assert next_unwind("long", D(200), units[:1], D("0.3"), buffer) is None
    assert next_unwind("long", D(200), [], D(1), buffer) is None


def test_a_shorts_grid_is_mirrored() -> None:
    units = [(D(100), D("0.3")), (D(105), D("0.3")), (D(109), D("0.3")), (D(113), D("0.3"))]
    buffer = unwind_buffer(D("0.0005"))
    # 113 kept to the close: 109 bought back at 105.
    assert next_unwind("short", D("105.1"), units, D("1.2"), buffer) is None
    sell = next_unwind("short", D(105), units, D("1.2"), buffer)
    assert sell == Signal("exit", "short", UNWIND_EXIT, close_fraction=D("0.3") / D("1.2"))
    # The lowest price is the highest unit: half the way from 113 below it.
    assert unwind_level(-1, [(D(100), D(1)), (D(113), D(1))], buffer) == D("93.5")


def test_max_margin_and_intraday_are_averaging_settings() -> None:
    _check_management("single", PositionManagement(intraday=False))
    with pytest.raises(HTTPException):
        _check_management("single", PositionManagement(intraday=True))
    with pytest.raises(HTTPException):
        _check_management("single", PositionManagement(max_margin_usd=D(5000)))


def test_a_signal_add_is_sized_like_the_first_entry_a_dip_add_at_add_terms() -> None:
    paper = Paper(
        kind="averaging",
        leverage=D(10),
        initial_size_usd=D(10),
        add_leverage=D(3),
        add_size_usd=None,
    )
    assert add_terms(paper, SIGNAL_ADD) == (D(10), D(10))
    assert add_terms(paper, AVERAGE_DOWN) == (D(10), D(3))  # add size defaults to initial
    paper.add_size_usd = D(20)
    assert add_terms(paper, AVERAGE_DOWN) == (D(20), D(3))
    paper.add_leverage = None
    assert add_terms(paper, AVERAGE_DOWN) is None


def test_an_intraday_take_profit_closes_at_once_on_the_whole_pnl() -> None:
    # $20 of margin behind a size of 1.3 at an average of 100: 2% is $0.40.
    args = (D(100), D("1.3"), D(20))
    assert take_profit_close("long", D("100.31"), *args, D(0), D("0.02")) == Signal(
        "exit", "long", TAKE_PROFIT_EXIT
    )
    assert take_profit_close("long", D("100.3"), *args, D(0), D("0.02")) is None  # $0.39
    assert take_profit_close("long", D("100.31"), *args, D(-1), D("0.02")) is None  # unwind loss


def test_the_levels_stay_put_unless_the_exchange_liquidates_sooner() -> None:
    # 1% at 10x: liquidated with 10% left - after the default 20%: unchanged.
    assert margin_levels(10, 100, 0.01) == pytest.approx((0.5, 0.3))
    assert margin_levels(10, 100, None) == pytest.approx((0.5, 0.3))
    # 6% at 10x: liquidated with 60% left - the add at 75%, the give-up at 65%.
    assert margin_levels(10, 100, 0.06) == pytest.approx((0.75, 0.65))


def test_live_an_early_liquidation_brings_the_add_up() -> None:
    # $10 behind a size of 1 at 100 (10x), 6% maintenance: the add at 97.5.
    def at(price: str) -> Signal | None:
        return managed_signal("long", D(price), D(100), D(1), D(10), D(100), None, 0.06)

    assert at("97.6") is None
    assert _reason(at("97.5")) == ("add", AVERAGE_DOWN)
    assert _reason(at("96.4")) == ("exit", OUT_OF_MARGIN_EXIT)  # 64% left


def test_a_signal_add_comes_once_per_candle_a_dip_add_once_per_buy() -> None:
    reading = datetime(2026, 10, 18, 1, 45, tzinfo=UTC)
    filled = datetime(2026, 10, 18, 1, 46, 10, tzinfo=UTC)  # an add filled after the reading
    # A filled signal add doesn't open the window again: the next pass finds it.
    assert add_window(SIGNAL_ADD, filled, reading) == reading
    # A dip add: from the last buy - a filled one lifted the margin left.
    assert add_window(AVERAGE_DOWN, filled, reading) == filled
    assert add_window(AVERAGE_DOWN, None, reading) == reading
    assert add_window(SIGNAL_ADD, filled, None) == filled
    assert add_window(AVERAGE_DOWN, None, None) is None
