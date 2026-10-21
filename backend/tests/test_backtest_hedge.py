"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta

import pytest

from app.backtest.averaging import (
    SEASON_END_EXIT,
    SEASON_REOPEN,
    Rules,
    simulate,
    states_after,
)
from app.backtest.bars import Bar, SimTrade
from app.backtest.hedge import (
    SHORT_ADD,
    SHORT_COVERED,
    SHORT_GIVE_UP,
    SHORT_HALF_COVERED,
    SHORT_MARGIN,
    SHORT_OPEN,
    SHORT_REDUCE,
    SHORT_SIDES,
    Hedge,
)

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def _at(k: int) -> datetime:
    return T0 + timedelta(hours=k)


def _hedge(*candles: tuple[float, float, float, float], bearish: bool = True) -> Hedge:
    bars = {_at(k): Bar(_at(k), *c) for k, c in enumerate(candles)}
    return Hedge(bars, set(bars) if bearish else set(), fee_rate=0.0)


FLAT = (1000.0, 1000.0, 1000.0, 1000.0)


def test_a_mirror_of_the_long_opens_on_a_bearish_close_in_loss() -> None:
    for long_pnl, bearish in ((-10, False), (10, True)):
        hedge = _hedge(FLAT, bearish=bearish)
        hedge.step(_at(0), long_pnl, 500, 100, 1000)
        assert hedge.short is None
    hedge = _hedge(FLAT)
    hedge.step(_at(0), -10, 500, 100, 1000)
    assert hedge.short is not None
    # The long's $500 on $100 mirrored: $100 of margin at its 5x.
    assert (hedge.short.margin, hedge.short.cost) == (100, 500)
    assert [(f.side, f.margin, f.notional) for f in hedge.take_fills()] == [(SHORT_OPEN, 100, 500)]


def test_the_budget_caps_the_short() -> None:
    hedge = _hedge(FLAT)
    hedge.step(_at(0), -10, 500, 100, 40)
    assert hedge.short is not None and hedge.short.margin == 40


def test_the_short_mirrors_the_longs_adds_and_sales_and_closes_once_covered() -> None:
    hedge = _hedge(FLAT, FLAT, (1000, 1000, 900, 900), (900, 900, 900, 900))
    hedge.step(_at(0), -10, 500, 100, 1000)
    # The long added $100 of margin for $500 at entry: the short the same.
    assert hedge.step(_at(1), -20, 1000, 200, 1000) == 0
    assert hedge.short is not None
    assert (hedge.short.cost, hedge.short.margin) == (1000, 200)
    # At 900 the short is +$100; the long sold down to $600 at entry (the pair
    # still -$50): 40% bought back, +$40 realized.
    assert hedge.step(_at(2), -150, 600, 120, 1000) == pytest.approx(40)
    assert hedge.short is not None
    assert hedge.short.cost == pytest.approx(600)
    assert hedge.short.margin == pytest.approx(120)
    # The long at -$50, the shorts +$40 realized and +$60 open: covered.
    assert hedge.step(_at(3), -50, 600, 120, 1000, realized=40) == pytest.approx(60)
    assert hedge.short is None
    fills = hedge.take_fills()
    assert [f.side for f in fills] == [SHORT_OPEN, SHORT_ADD, SHORT_REDUCE, SHORT_COVERED]
    assert [f.pnl for f in fills[2:]] == [pytest.approx(40), pytest.approx(60)]


def test_the_short_is_never_reduced_at_a_loss() -> None:
    hedge = _hedge(FLAT, (1000, 1050, 1000, 1050))
    hedge.step(_at(0), -10, 500, 100, 1000)
    hedge.step(_at(1), -10, 300, 60, 1000)  # the long shrank but the short is -$25
    assert hedge.short is not None and hedge.short.margin == 100


def test_the_short_gives_up_before_its_liquidation() -> None:
    # $500 short at 1000 on $100: 30% of its margin left at 1140.
    hedge = _hedge(FLAT, (1000, 1150, 1000, 1100))
    hedge.step(_at(0), -10, 500, 100, 1000)
    assert hedge.step(_at(1), -10, 500, 100, 1000) == pytest.approx(-70)
    assert hedge.take_fills()[-1].side == SHORT_GIVE_UP


def _entry(k: int, price: float) -> SimTrade:
    return SimTrade("long", _at(k), price, None, entry_reason="regime_entry")


# $10 at 10x; $10 dip adds at 3x; TP +30%; the automatic give-up only.
RULES = Rules(10, 10, 3, 10, 0.3, None, 0.2)
# Entered at 100, signal adds at 120 and 105 (kept: above the first buy), then
# a bounce to 105.5 with the position still in loss.
LONG = [
    Bar(_at(0), 100, 100, 100, 100),
    Bar(_at(1), 120, 120, 120, 120),
    Bar(_at(2), 105, 105, 105, 105),
    Bar(_at(3), 105, 105.5, 104, 105),
]
ENTRIES = [_entry(0, 100), _entry(1, 120), _entry(2, 105)]


def test_in_loss_and_bearish_a_signal_unit_is_sold_at_a_profit() -> None:
    hedge = _hedge(FLAT, FLAT, FLAT, FLAT)
    [t] = simulate(LONG, ENTRIES, RULES, hedge=hedge)
    sells = [f for f in t.fills if f.side == "sell"]
    # The 105 unit at 105 + the 0.4% unwind markup; the 120 one stays.
    assert [f.time for f in sells] == [_at(3)]
    assert sells[0].price == pytest.approx(105.42)
    assert sells[0].notional == pytest.approx(100 / 105 * 105.42)
    # Without the hedge (not bearish) it's kept.
    [t] = simulate(LONG, ENTRIES, RULES, hedge=_hedge(FLAT, FLAT, FLAT, FLAT, bearish=False))
    assert not [f for f in t.fills if f.side == "sell"]


def test_the_shorts_fills_go_with_the_position_and_leave_its_state() -> None:
    hedge = _hedge(FLAT, FLAT, FLAT, FLAT)
    [t] = simulate(LONG, ENTRIES, RULES, hedge=hedge)
    shorts = [f for f in t.fills if f.side in SHORT_SIDES]
    assert shorts and shorts[0].side == SHORT_OPEN and shorts[0].time == _at(2)
    states = states_after(list(t.fills), 0.2)
    k = t.fills.index(shorts[0])
    assert states[k] == states[k - 1]
    # The peak margin counts the short's.
    assert t.margin > 30


def test_the_shorts_realized_profit_counts_toward_covering_the_long() -> None:
    hedge = _hedge(FLAT, FLAT)
    hedge.step(_at(0), -100, 500, 100, 1000)
    # The open short at 0, but $100 already realized by its reduces: covered.
    assert hedge.step(_at(1), -100, 500, 100, 1000, realized=100) == 0
    assert hedge.short is None
    assert hedge.take_fills()[-1].side == SHORT_COVERED
    # No new short while the pair isn't in loss.
    hedge = _hedge(FLAT)
    hedge.step(_at(0), -100, 500, 100, 1000, realized=100)
    assert hedge.short is None


def test_a_short_covering_the_longs_loss_closes_alone() -> None:
    long_bars = [
        Bar(_at(0), 100, 100, 100, 100),
        Bar(_at(1), 99, 99, 99, 99),  # bearish, in loss: the short opens
        Bar(_at(2), 99, 99, 99, 99),  # still bearish, ETH -10%: covered
        Bar(_at(3), 98, 98, 98, 98),
    ]
    eth = [FLAT, FLAT, (1000, 1000, 900, 900), (900, 900, 900, 900)]
    bars = {_at(k): Bar(_at(k), *c) for k, c in enumerate(eth)}
    t, *_ = simulate(long_bars, [_entry(0, 100)], RULES, hedge=Hedge(bars, {_at(1), _at(2)}, 0.0))
    # The short closed at 2, the long held on - closed only at 3, the bear
    # phase over in profit (a new bottom).
    covered = [f for f in t.fills if f.side == SHORT_COVERED]
    assert [f.time for f in covered] == [_at(2)]
    assert (t.closed_at, t.exit_reason) == (_at(3), SEASON_END_EXIT)


def test_a_short_opens_only_once_the_long_needs_support() -> None:
    # A $5,000 max margin: the long needs $1,000 (20%) of margin for a short.
    hedge = _hedge(FLAT, FLAT)
    hedge.max_margin = 5000
    hedge.step(_at(0), -50, 3000, 600, 5000)
    assert hedge.short is None
    hedge.step(_at(1), -80, 5000, 1000, 5000)
    assert hedge.short is not None and hedge.short.margin == 1000


def test_after_the_bear_phase_a_profitable_long_closes_and_reopens() -> None:
    long_bars = [
        Bar(_at(0), 100, 100, 100, 100),
        Bar(_at(1), 99, 99, 99, 99),  # bearish, in loss: the short opens
        Bar(_at(2), 101, 101, 101, 101),  # still bearish: the long's gain covers the short
        Bar(_at(3), 101, 101, 101, 101),  # not bearish any more, in profit
        Bar(_at(4), 101, 101, 101, 101),
    ]
    bars = {_at(k): Bar(_at(k), *FLAT) for k in range(5)}
    hedge = Hedge(bars, {_at(1), _at(2)}, fee_rate=0.0)
    first, second = simulate(long_bars, [_entry(0, 100)], RULES, hedge=hedge)
    assert (first.closed_at, first.close_price, first.exit_reason) == (_at(3), 101, SEASON_END_EXIT)
    assert first.total_pnl_usd > 0
    assert (second.opened_at, second.entry_reason) == (_at(3), SEASON_REOPEN)
    assert second.entry_price == 101


def test_the_short_mirrors_the_longs_margin_and_leverage() -> None:
    hedge = _hedge(FLAT, FLAT)
    hedge.step(_at(0), -41, 1455, 100, 1000)  # $1,455 on $100: x14.55
    assert hedge.short is not None
    assert hedge.short.margin == pytest.approx(100)
    assert hedge.short.cost == pytest.approx(1455)
    # A dip add of $30 at 5x ($150): the short adds the same $30 for $150.
    hedge.step(_at(1), -60, 1605, 130, 1000)
    assert hedge.short.margin == pytest.approx(130)
    assert hedge.short.cost == pytest.approx(1605)


def test_no_top_up_once_bullish_or_with_the_pair_in_profit() -> None:
    hedge = _hedge(FLAT, FLAT, bearish=False)
    hedge.bearish = {_at(0)}
    hedge.step(_at(0), -10, 500, 100, 1000)
    hedge.step(_at(1), -10, 1000, 200, 1000)  # the long grew, but bullish now
    assert hedge.short is not None and hedge.short.cost == 500
    hedge = _hedge(FLAT, FLAT)
    hedge.step(_at(0), -10, 500, 100, 1000)
    hedge.step(_at(1), -10, 1000, 200, 1000, realized=5)  # bearish, the pair -$5: tops up
    assert hedge.short is not None and hedge.short.cost == 1000


def test_a_hedged_take_profit_counts_the_shorts() -> None:
    # Entered at 100, bearish and in loss at 95 (a short of the long), then
    # the strategy sells at 104: the long +$4 is +40% of its $10, but the
    # short, ETH up 20%, is -$20 - the pair in loss: no take-profit.
    long_bars = [
        Bar(_at(0), 100, 100, 100, 100),
        Bar(_at(1), 95, 95, 95, 95),
        Bar(_at(2), 104, 104, 104, 104),
    ]
    eth = [FLAT, FLAT, (1200, 1200, 1200, 1200)]
    bars = {_at(k): Bar(_at(k), *c) for k, c in enumerate(eth)}
    sell = _entry(0, 100)
    sell.closed_at, sell.close_price, sell.exit_reason = _at(2), 104.0, "hh_rejection"
    [t] = simulate(long_bars, [sell], RULES, hedge=Hedge(bars, {_at(1)}, fee_rate=0.0))
    assert t.exit_reason == "open_at_end"
    # Without the hedge the same sell takes profit.
    [t] = simulate(long_bars, [sell], RULES)
    assert t.exit_reason == "take_profit:hh_rejection"


def _bounce(high: float, top_up: float = 50) -> Hedge:
    """$1,750 on $100 at 2424.35 (x17.5), bearish, then a candle up to `high`."""
    flat = Bar(_at(0), *(2424.35,) * 4)
    up = Bar(_at(1), 2424.35, high, 2424.35, 2424.35)
    return Hedge({_at(0): flat, _at(1): up}, {_at(0), _at(1)}, fee_rate=0.0, top_up=top_up)


def test_a_bounce_in_the_bear_phase_tops_the_short_up_instead_of_giving_up() -> None:
    # Half its margin lost at ~2493.6, given up at ~2521.3. Up to 2510: one
    # $50 top-up (the next half lost at ~2528.3) - held, the size unchanged.
    hedge = _bounce(2510)
    hedge.step(_at(0), -10, 1750, 100, 1000)
    assert hedge.step(_at(1), -10, 1750, 100, 1000) == 0
    assert hedge.short is not None
    assert (hedge.short.margin, hedge.short.cost) == (150, 1750)
    assert [f.side for f in hedge.take_fills()] == [SHORT_OPEN, SHORT_MARGIN]
    # Up to 2528.64 (30 Aug): two top-ups, still held.
    hedge = _bounce(2528.64)
    hedge.step(_at(0), -10, 1750, 100, 1000)
    hedge.step(_at(1), -10, 1750, 100, 1000)
    assert hedge.short is not None and hedge.short.margin == 200
    # No budget for a top-up: the give-up, as before.
    hedge = _bounce(2528.64)
    hedge.step(_at(0), -10, 1750, 100, 1000)
    hedge.step(_at(1), -10, 1750, 100, 40)
    assert hedge.short is None
    assert hedge.take_fills()[-1].side == SHORT_GIVE_UP


def test_with_big_margins_a_short_covering_half_the_loss_closes() -> None:
    # The long and the short $1,000 each of a $5,000 max margin: the long
    # -$200, the short (ETH -4%) +$200... at -2% +$100 - half of it: banked.
    drop = (1000.0, 1000.0, 980.0, 980.0)
    bars = {_at(0): Bar(_at(0), *FLAT), _at(1): Bar(_at(1), *drop)}
    hedge = Hedge(bars, {_at(0), _at(1)}, 0.0, max_margin=5000)
    hedge.step(_at(0), -50, 5000, 1000, 5000)
    assert hedge.step(_at(1), -200, 5000, 1000, 5000) == pytest.approx(100)
    assert hedge.short is None
    assert hedge.take_fills()[-1].side == SHORT_HALF_COVERED
    # Under half of the loss (the long -$250): held.
    hedge = Hedge(bars, {_at(0), _at(1)}, 0.0, max_margin=5000)
    hedge.step(_at(0), -50, 5000, 1000, 5000)
    hedge.step(_at(1), -250, 5000, 1000, 5000)
    assert hedge.short is not None
