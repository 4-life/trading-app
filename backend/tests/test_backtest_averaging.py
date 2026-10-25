"""Pure unit tests, no database."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.backtest.averaging import Rules, in_trend, simulate, states_after
from app.backtest.bars import Bar, Fill, SimTrade
from app.backtest.sweep import drained_at
from app.executors.position_management import (
    MAX_DRAWDOWN_EXIT,
    OUT_OF_MARGIN_EXIT,
    REOPEN_IN_TREND,
    TAKE_PROFIT_EXIT,
)

T0 = datetime(2026, 10, 1, tzinfo=UTC)
# Plan F: $10 at 10x, then $10 at 3x whenever half the margin is lost; TP +30%, give-up -40%.
PLAN_F = Rules(10, 10, 3, 10, 0.3, 0.4, 0.2)


def _bars(*candles: tuple[float, float, float, float]) -> list[Bar]:
    return [Bar(T0 + timedelta(hours=k), *c) for k, c in enumerate(candles)]


def _entry(
    k: int,
    price: float = 100.0,
    direction: str = "long",
    sell_at: tuple[int, float] | None = None,
) -> SimTrade:
    """The strategy's trade: entered on candle `k`, sold (`sell_at`: candle, price)."""
    t = SimTrade(direction, T0 + timedelta(hours=k), price, None, entry_reason="regime_entry")
    if sell_at is not None:
        t.closed_at, t.close_price = T0 + timedelta(hours=sell_at[0]), sell_at[1]
        t.exit_reason = "hh_rejection"
    return t


def test_an_add_at_half_the_margin_lost_then_the_sell_above_the_take_profit() -> None:
    # $100 at 100 ($10 margin): half of it is lost at 95; the strategy sells at 130.
    bars = _bars((100, 100, 100, 100), (100, 100, 94.5, 96), (96, 131, 96, 130))
    [t] = simulate(bars, [_entry(0, sell_at=(2, 130))], PLAN_F)
    assert t.adds == 1
    assert t.margin == 20
    # Its fills for the chart: the first entry, the add at its level - the
    # lowest unit, kept to the close - and the first entry sold back in profit
    # on the way up (its price + 0.4%), before the strategy's sell.
    assert [(f.side, f.time, f.price) for f in t.fills] == [
        ("buy", T0, 100),
        ("buy", T0 + timedelta(hours=1), 95),
        ("sell", T0 + timedelta(hours=2), pytest.approx(100.4)),
    ]
    # $100 at 100 and $30 at 95: the next add would be at ~90.7, not reached.
    assert t.entry_price == pytest.approx(130 / (1 + 30 / 95))
    assert (t.exit_reason, t.close_price) == (f"{TAKE_PROFIT_EXIT}:hh_rejection", 130)


def test_a_short_is_the_long_mirrored() -> None:
    # $100 short at 100 ($10 margin): half of it is lost at 105; the strategy
    # buys back at 70.
    bars = _bars((100, 100, 100, 100), (100, 105.5, 100, 104), (104, 104, 69, 70))
    short = replace(PLAN_F, direction="short")
    [t] = simulate(bars, [_entry(0, direction="short", sell_at=(2, 70))], short)
    assert t.adds == 1
    assert t.margin == 20
    # The first sell, the add at its level - the highest unit, kept to the
    # close - and the first sell bought back in profit on the way down (its
    # price - 0.4%), before the strategy's exit.
    assert [(f.side, f.time, f.price) for f in t.fills] == [
        ("buy", T0, 100),
        ("buy", T0 + timedelta(hours=1), 105),
        ("sell", T0 + timedelta(hours=2), pytest.approx(99.6)),
    ]
    assert t.entry_price == pytest.approx(130 / (1 + 30 / 105))
    assert (t.exit_reason, t.close_price) == (f"{TAKE_PROFIT_EXIT}:hh_rejection", 70)
    assert t.pnl_usd > 0
    # A long's entries open no short.
    assert simulate(bars, [_entry(0, sell_at=(2, 70))], short) == []


def test_a_short_gives_up_above_the_first_sell() -> None:
    # No budget for an add: the automatic give-up once 70% of the $10 margin
    # is lost - at 107, on the way up (before the 40% drawdown's 140).
    bars = _bars((100, 100, 100, 100), (100, 150, 100, 145))
    rules = replace(PLAN_F, direction="short", max_margin=10)
    [t] = simulate(bars, [_entry(0, direction="short")], rules)
    assert t.exit_reason == OUT_OF_MARGIN_EXIT
    assert t.close_price == pytest.approx(107)
    assert t.give_up_price == pytest.approx(140)
    assert t.pnl_usd == pytest.approx(-7)


def test_both_takes_each_positions_direction_from_its_entry() -> None:
    # A long opens at 100; the short signal while it's open adds nothing; the
    # strategy sells it at 130 (take-profit) and a short opens there.
    bars = _bars((100, 100, 100, 100), (100, 101, 99, 100), (100, 131, 100, 130))
    both = replace(PLAN_F, direction="both")
    entries = [_entry(0, sell_at=(2, 130)), _entry(1, direction="short"), _entry(2, 130, "short")]
    long, short = simulate(bars, entries, both)
    assert (long.direction, long.adds, long.exit_reason) == (
        "long",
        0,
        f"{TAKE_PROFIT_EXIT}:hh_rejection",
    )
    assert (short.direction, short.opened_at, short.entry_price) == ("short", bars[2].time, 130)
    assert short.exit_reason == "open_at_end"


def test_a_sell_below_the_take_profit_is_ignored_the_position_holds() -> None:
    # $100 at 100 on $10 of margin: a sell at 102 is +$2 = 20% - under the 30% floor.
    bars = _bars((100, 100, 100, 100), (100, 103, 100, 102), (102, 102, 101, 101))
    [t] = simulate(bars, [_entry(0, sell_at=(1, 102))], PLAN_F)
    assert t.exit_reason == "open_at_end"


def test_adds_at_3x_reach_the_give_up_before_liquidation() -> None:
    bars = _bars((100, 100, 100, 100), (100, 100, 55, 56))
    [t] = simulate(bars, [_entry(0)], PLAN_F)
    assert t.exit_reason == MAX_DRAWDOWN_EXIT
    assert t.close_price == pytest.approx(60)
    assert t.adds > 5


def test_higher_leverage_adds_need_far_more_margin_to_hold() -> None:
    bars = _bars((100, 100, 100, 100), (100, 100, 55, 56))
    [low] = simulate(bars, [_entry(0)], PLAN_F)
    [high] = simulate(bars, [_entry(0)], Rules(10, 10, 10, 10, 0.3, 0.4, 0.2))
    # Down to the -40% give-up: 40 adds, $410 at 3x - over 9,000 adds, ~$96k at 10x.
    assert (low.adds, low.margin) == (40, 410)
    assert high.margin > 200 * low.margin


def test_a_gap_below_the_add_level_fills_at_the_open() -> None:
    bars = _bars((100, 100, 100, 100), (93, 94, 92.5, 93))
    trades = simulate(bars, [_entry(0)], PLAN_F)
    # Opened at 93 - under the 95 level: the add fills at 93; the next level (~90.7) isn't reached.
    assert trades[0].adds == 1
    assert trades[0].fills[1].price == 93


def test_only_long_entries_and_one_position_at_a_time() -> None:
    bars = _bars(*[(100, 100, 100, 100)] * 3, (100, 131, 100, 130), (130, 130, 130, 130))
    entries = [_entry(0, direction="short"), _entry(1, sell_at=(3, 130)), _entry(2), _entry(4, 130)]
    trades = simulate(bars, entries, PLAN_F)
    # The short is ignored, the entry at 2 lands while the position is open,
    # the one at 4 opens the next position after the sell at the take-profit.
    assert [t.opened_at for t in trades] == [T0 + timedelta(hours=1), T0 + timedelta(hours=4)]
    assert [t.exit_reason for t in trades] == [f"{TAKE_PROFIT_EXIT}:hh_rejection", "open_at_end"]


def test_trading_starts_at_the_start_date() -> None:
    bars = _bars(*[(100, 100, 100, 100)] * 3)
    trades = simulate(bars, [_entry(0), _entry(2)], PLAN_F, start=T0 + timedelta(hours=1))
    assert [t.opened_at for t in trades] == [T0 + timedelta(hours=2)]


def test_the_position_after_each_buy() -> None:
    # Plan F: $10 at 10x at 100, then $10 at 3x at 99.
    first, add = states_after([Fill(T0, 100, 10, 100), Fill(T0, 99, 10, 30)], 0.2)
    assert (first.margin, first.entry, first.leverage, first.pnl_usd) == (10, 100, 10, 0)
    assert first.liquidation == pytest.approx(92)  # 80% of the $10 margin = 8% of price
    size = 1 + 30 / 99
    assert add.margin == 20
    assert add.entry == pytest.approx(130 / size)
    assert add.leverage == pytest.approx(6.5)
    assert add.liquidation == pytest.approx(130 / size - 16 / size)
    assert add.pnl_usd == pytest.approx(size * 99 - 130)


def _zigzag() -> list[Bar]:
    """Rising: 5 candles up, 5 down, each leg higher."""
    bars: list[Bar] = []
    for leg in range(12):
        for k in range(5):
            p = 100 + leg * 2 + (k if leg % 2 == 0 else 4 - k)
            bars.append(Bar(T0 + timedelta(hours=len(bars)), p, p + 0.5, p - 0.5, p))
    return bars


def test_every_strategy_entry_signal_adds_to_the_open_position() -> None:
    bars = _zigzag()
    # Entered at 108 (candle 20); the strategy signals again on candles 30 and 35.
    entries = [_entry(20, 108), _entry(30, bars[30].close), _entry(35, bars[35].close)]
    [t] = simulate(bars, entries, PLAN_F)
    assert [(f.time, f.price) for f in t.fills] == [
        (T0 + timedelta(hours=20), 108),
        (T0 + timedelta(hours=30), bars[30].close),
        (T0 + timedelta(hours=35), bars[35].close),
    ]
    assert t.fills[1].notional == 100  # sized like the first entry: $10 at 10x


def test_each_unit_but_the_lowest_is_sold_at_its_own_price_plus_the_markup() -> None:
    # $100 at 100, $30 adds at 95 and ~91.2, then back to 101.
    bars = _bars((100, 100, 100, 100), (100, 100, 91, 92), (92, 101, 92, 100), (100, 100, 99, 99))
    [t] = simulate(bars, [_entry(0)], PLAN_F)
    assert [f.side for f in t.fills] == ["buy", "buy", "buy", "sell", "sell"]
    lowest = t.fills[2].price
    # The 95 unit, then the first buy, each at its own price + 0.4% (the
    # markup; no fees here); the lowest kept.
    prices = [f.price for f in t.fills]
    assert prices == [100, 95, lowest, pytest.approx(95.38), pytest.approx(100.4)]
    assert t.fills[3].notional == pytest.approx(30 / 95 * 95.38)
    assert t.fills[3].pnl == pytest.approx(30 / 95 * (95.38 - 95))  # its unit's profit
    size = 1 + 30 / 95 + 30 / lowest
    assert t.fills[3].margin == pytest.approx(30 * (30 / 95) / size)  # its share of the margin
    assert t.adds == 2 and t.margin == 30  # all the margin put in
    # Held to the end at 99: the lowest only; PnL = sold + held, at the average.
    average = 160 / size
    sold = 30 / 95 * (95.38 - average) + 1 * (100.4 - average)
    assert t.pnl_usd == pytest.approx(sold + 30 / lowest * (99 - average))


def test_the_position_after_an_unwind() -> None:
    fills = [Fill(T0, 100, 10, 100), Fill(T0, 95, 10, 30), Fill(T0, 100, 0, 30 / 95 * 100, "sell")]
    *_, after = states_after(fills, 0.2)
    size = 1 + 30 / 95
    assert after.margin == pytest.approx(20 * (1 - (30 / 95) / size))
    assert after.entry == pytest.approx(130 / size)  # an unwind doesn't move the average


def test_with_three_dip_units_a_bounce_sells_the_two_above_the_lowest_together() -> None:
    down = _bars((100, 100, 100, 100), (100, 100, 85, 86))
    [deep] = simulate(down, [_entry(0)], PLAN_F)
    *_, third, second, _lowest = [f.price for f in deep.fills]
    assert len(deep.fills) - 1 >= 3  # 3 dip units or more: pairs
    # The second-lowest unit's own price + 0.4% isn't enough any more: held.
    early = _bars((100, 100, 100, 100), (100, 100, 85, 86), (86, second * 1.004, 86, 86))
    [t] = simulate(early, [_entry(0)], PLAN_F)
    assert not [f for f in t.fills if f.side == "sell"]
    # Up to the pair's higher unit (+0.4%): both sold in one fill, the lowest kept.
    level = third * 1.004
    bounce = _bars((100, 100, 100, 100), (100, 100, 85, 86), (86, level, 86, level - 0.1))
    [t] = simulate(bounce, [_entry(0)], PLAN_F)
    sells = [f for f in t.fills if f.side == "sell"]
    assert [f.price for f in sells] == [pytest.approx(level)]
    size = 10 * 3 / second + 10 * 3 / third  # each $10 at 3x
    assert sells[0].notional == pytest.approx(size * level)
    profit = 10 * 3 / second * (level - second) + 10 * 3 / third * (level - third)
    assert sells[0].pnl == pytest.approx(profit)


def test_adds_stop_at_the_max_margin_and_the_position_gives_up_before_liquidation() -> None:
    # $30 of cash: the first $10 and two $10 adds, then no more - long before -40%.
    capped = Rules(10, 10, 3, 10, 0.3, 0.4, 0.2, max_margin=30)
    bars = _bars((100, 100, 100, 100), (100, 100, 55, 56))
    [t] = simulate(bars, [_entry(0)], capped)
    assert t.adds == 2
    assert t.margin == 30
    # Closed with 30% of its margin left - above the liquidation (20%), above 60.
    assert t.exit_reason == OUT_OF_MARGIN_EXIT
    assert t.pnl_usd == pytest.approx(-21)
    assert t.close_price > 60

    # Without max_drawdown: the automatic give-up alone.
    automatic = Rules(10, 10, 3, 10, 0.3, None, 0.2, max_margin=30)
    [same] = simulate(bars, [_entry(0)], automatic)
    assert (same.exit_reason, same.give_up_price) == (OUT_OF_MARGIN_EXIT, None)
    assert same.close_price == pytest.approx(t.close_price)


def test_the_margin_is_the_peak_locked_at_once_not_every_rebuy_summed() -> None:
    # $10 adds at 95 and ~91.2, the 95 one and the first buy sold back on the
    # way to 101 (releasing their share by size), then the next dip adds $10
    # again: $40 put in, $30 the most locked at once.
    bars = _bars(
        (100, 100, 100, 100),
        (100, 100, 91, 92),
        (92, 101, 92, 100),
        (100, 100, 88, 89),
    )
    [t] = simulate(bars, [_entry(0)], PLAN_F)
    assert [f.side for f in t.fills] == ["buy", "buy", "buy", "sell", "sell", "buy"]
    assert t.margin == pytest.approx(30)


def test_an_intraday_paper_takes_profit_at_once_and_keeps_going() -> None:
    intraday = Rules(10, 10, 3, 10, 0.02, 0.4, 0.2, intraday=True)
    # $100 at 100 on $10: 2% of the margin ($0.20) at 100.20; the strategy enters again at 2.
    bars = _bars((100, 100, 100, 100), (100, 100.5, 99.9, 100.4), (100.4, 100.4, 100.3, 100.4))
    trades = simulate(bars, [_entry(0), _entry(2, 100.4)], intraday)
    assert trades[0].exit_reason == TAKE_PROFIT_EXIT
    assert trades[0].close_price == pytest.approx(100.2)
    assert trades[1].opened_at == T0 + timedelta(hours=2)  # no stop after the take-profit


def test_a_signal_while_the_strategys_own_trade_is_open_still_adds() -> None:
    bars = _zigzag()
    # The strategy's trade: in at candle 20, held past 35 - its signal at 30 opens no trade.
    trade = _entry(20, 108, sell_at=(59, bars[59].close))
    signal = _entry(30, bars[30].close)
    [t] = simulate(bars, [trade], PLAN_F, signals_held=[signal])
    assert [f.time for f in t.fills][:2] == [T0 + timedelta(hours=20), T0 + timedelta(hours=30)]


def test_the_max_margin_caps_every_position_wins_banked_and_a_give_up_doesnt_end_it() -> None:
    # $31 of cash; an intraday paper's +200% take-profit at once: $20 a win.
    rules = Rules(10, 10, 3, 10, 2.0, 0.4, 0.2, max_margin=31, intraday=True)
    bars = _bars(
        (100, 100, 100, 100),
        (100, 121, 100, 120),  # +$20: $51 of cash, still $31 to lock
        (100, 100, 100, 100),
        (100, 100, 55, 56),  # given up with $30 locked: -$21 (70%), $30 left
        (56, 56, 56, 56),
    )
    trades = simulate(bars, [_entry(0), _entry(2), _entry(4, 56)], rules)
    assert [t.exit_reason for t in trades] == [TAKE_PROFIT_EXIT, OUT_OF_MARGIN_EXIT, "open_at_end"]
    # The win isn't put back in: $10 + two $10 adds, as with $31 alone.
    assert trades[1].adds == 2
    assert trades[1].margin == 30
    assert trades[1].pnl_usd == pytest.approx(-21)
    # $30 left after the loss: the next entry still opens.
    assert trades[2].opened_at == T0 + timedelta(hours=4)


def test_a_drained_budget_opens_nothing() -> None:
    # $30: given up with all of it locked, -$21 - $9 left, under the $10 entry.
    rules = Rules(10, 10, 3, 10, 0.3, 0.4, 0.2, max_margin=30)
    bars = _bars((100, 100, 100, 100), (100, 100, 55, 56), (56, 56, 56, 56))
    trades = simulate(bars, [_entry(0), _entry(2, 56)], rules)
    assert [t.exit_reason for t in trades] == [OUT_OF_MARGIN_EXIT]


def test_an_early_exchange_liquidation_moves_the_give_up_up_before_it() -> None:
    # $750 at 50x, no adds (the max margin): the exchange's 1% maintenance
    # liquidates at ~98.99 (50% of the margin left) - the give-up moves up
    # with it, to 56.25% left: 99.125, before it.
    rules = Rules(50, 750, 5, 750, 0.2, None, 0.2, max_margin=750, maintenance_notional=0.01)
    bars = _bars((100, 100, 100, 100), (100, 100, 98, 98.5))
    [t] = simulate(bars, [_entry(0)], rules)
    assert t.exit_reason == OUT_OF_MARGIN_EXIT
    assert t.close_price == pytest.approx(99.125)
    assert t.pnl_usd == pytest.approx(-328.125)  # not the whole $750


def test_a_high_maintenance_margin_brings_the_add_before_the_liquidation() -> None:
    # ENA: $20 at 10x, 6% maintenance - liquidated at ~-4.3% (60% left),
    # before the default add at -5% (50% left). The add moves up to 75% left:
    # -2.5%, at 97.5.
    rules = Rules(10, 20, 5, 20, 0.5, None, 0.2, max_margin=1000, maintenance_notional=0.06)
    bars = _bars((100, 100, 100, 100), (100, 100, 97, 97.5), (97.5, 98, 97.5, 98))
    [t] = simulate(bars, [_entry(0)], rules)
    assert t.exit_reason == "open_at_end"
    assert [(f.price, f.margin) for f in t.fills] == [(100, 20), (pytest.approx(97.5), 20)]


def test_compounding_puts_the_wins_back_in() -> None:
    # As above, compounding: the +$20 win makes $51 of cash, all of it the
    # next position's budget - four $10 adds instead of two.
    rules = Rules(10, 10, 3, 10, 2.0, 0.4, 0.2, max_margin=31, intraday=True, compound=True)
    bars = _bars(
        (100, 100, 100, 100),
        (100, 121, 100, 120),
        (100, 100, 100, 100),
        (100, 100, 55, 56),
        (56, 56, 56, 56),
    )
    trades = simulate(bars, [_entry(0), _entry(2), _entry(4, 56)], rules)
    assert [t.exit_reason for t in trades] == [TAKE_PROFIT_EXIT, OUT_OF_MARGIN_EXIT, "open_at_end"]
    assert trades[1].adds == 4
    assert trades[1].margin == 50


# $100 at 100 on $10: the take-profit (2% of the margin) at 100.20 on candle 1.
_REOPEN_BARS = ((100, 100, 100, 100), (100, 100.5, 99.9, 100.4), (100.4, 100.4, 100.3, 100.4))


def test_reopen_in_trend_opens_a_fresh_position_at_the_take_profit_candles_close() -> None:
    rules = Rules(10, 10, 3, 10, 0.02, 0.4, 0.2, intraday=True, reopen=True)
    trades = simulate(_bars(*_REOPEN_BARS), [_entry(0)], rules)  # the strategy's trade held
    assert [t.exit_reason for t in trades] == [TAKE_PROFIT_EXIT, "open_at_end"]
    again = trades[1]
    assert (again.opened_at, again.entry_reason) == (T0 + timedelta(hours=1), REOPEN_IN_TREND)
    assert again.entry_price == pytest.approx(100.4)  # the candle's close
    assert again.adds == 0 and again.margin == pytest.approx(10)  # fresh: the initial size


def test_reopen_in_trend_waits_once_the_strategy_has_sold() -> None:
    rules = Rules(10, 10, 3, 10, 0.02, 0.4, 0.2, intraday=True, reopen=True)
    sold = _entry(0, sell_at=(1, 100.4))  # the trend ended on the take-profit's candle
    trades = simulate(_bars(*_REOPEN_BARS), [sold], rules)
    assert [t.exit_reason for t in trades] == [TAKE_PROFIT_EXIT]


def test_without_reopen_an_intraday_paper_trades_as_before() -> None:
    bars = _bars(*_REOPEN_BARS)
    for rules in (
        Rules(10, 10, 3, 10, 0.02, 0.4, 0.2, intraday=True),
        Rules(10, 10, 3, 10, 0.02, 0.4, 0.2, reopen=True),  # not intraday: no effect
    ):
        before = simulate(bars, [_entry(0)], replace(rules, reopen=False))
        assert simulate(bars, [_entry(0)], rules) == before


def test_the_trend_lasts_from_the_entry_to_before_the_sell() -> None:
    bars = _bars(*(_REOPEN_BARS * 2))
    held = in_trend(bars, [_entry(1, sell_at=(4, 100)), _entry(5)])
    assert held == {T0 + timedelta(hours=k) for k in (1, 2, 3, 5)}


def test_drained_at_the_close_that_takes_the_cash_under_the_initial_size() -> None:
    # $30 of cash, $10 positions: three give-ups of ~$7 leave it under $10 at the second.
    bars = _bars(
        (100, 100, 100, 100),
        (100, 100, 50, 50),
        (50, 50, 50, 50),
        (50, 50, 25, 25),
        (25, 25, 25, 25),
    )
    rules = replace(PLAN_F, max_margin=30)
    trades = simulate(bars, [_entry(0), _entry(2, 50), _entry(4, 25)], rules)
    drained = drained_at(trades, rules)
    cash = 30 + sum(t.pnl_usd for t in trades if t.closed_at <= (drained or T0))
    assert drained is not None and cash < 10
    assert drained_at(trades, replace(rules, max_margin=None)) is None
