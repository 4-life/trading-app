"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta

from app.backtest.averaging import Rules, simulate
from app.backtest.bars import Bar, SimTrade, exit_at
from app.executors.keltner_averaging import DEAD_EXIT, KeltnerGuard
from app.executors.position_management import TAKE_PROFIT_EXIT

T0 = datetime(2026, 10, 1, tzinfo=UTC)
# $10 at 10x ($100 at 100: one unit), TP 30% of the margin ($3); adds at half the margin lost (95).
RULES = Rules(10, 10, 3, 10, 0.3, 0.4, 0.2)


def _guard(
    closes: list[float],
    trend: int = -1,
    line: list[float | None] | None = None,
    sell: frozenset[int] = frozenset(),
    lows: dict[int, float] | None = None,
) -> KeltnerGuard:
    """`lows`: an LL's price by the candle confirming it."""
    n = len(closes)
    flat: list[float | None] = [90.0] * n
    low: list[tuple[float, int] | None] = []
    for i in range(n):
        last = low[-1] if low else None
        low.append((lows[i], i) if lows and i in lows else last)
    return KeltnerGuard(
        closes,
        [trend] * n,
        line if line is not None else flat,
        [False] * n,
        [i in sell for i in range(n)],
        low,
        [None] * n,
    )


def _bars(closes: list[float]) -> list[Bar]:
    return [Bar(T0 + timedelta(hours=k), c, c + 0.5, c - 0.5, c) for k, c in enumerate(closes)]


def _buy(k: int, price: float) -> SimTrade:
    return SimTrade("long", T0 + timedelta(hours=k), price, None, entry_reason="keltner_buy")


def test_a_long_opens_on_a_red_supertrend_only() -> None:
    g = _guard([100.0, 100.0])
    assert g.may_open("long", 0)
    assert not g.may_open("short", 0)
    green = _guard([100.0], trend=1)
    assert green.may_open("short", 0)
    assert not green.may_open("long", 0)


def test_the_dead_line_is_the_last_confirmed_ll_unless_the_entry_was_below_it() -> None:
    g = _guard([100.0] * 6, lows={1: 98.0, 4: 85.0})
    assert g.stop("long", 2, 2, 100.0) == 98.0
    # Opened at 90, under the LL at 98: broken - none until the next LL.
    assert g.stop("long", 3, 2, 90.0) is None
    assert g.stop("long", 4, 2, 90.0) == 85.0


def test_a_position_dies_on_a_close_below_it_in_loss() -> None:
    g = _guard([100.0, 97.0], lows={0: 98.0})
    assert g.dies("long", 1, 0, 100.0, pnl=-3.0)
    assert not g.dies("long", 1, 0, 100.0, pnl=1.0)
    assert not g.dies("long", 0, 0, 100.0, pnl=-3.0)  # the close at 100


def test_the_first_sell_is_broken_while_the_supertrend_line_stays() -> None:
    g = _guard([100.0] * 4, sell=frozenset({1, 2}))
    assert g.sell_broken("long", 1, 0)
    assert not g.sell_broken("long", 2, 0)  # the second
    moved = _guard([100.0] * 2, line=[90.0, 91.0], sell=frozenset({1}))
    assert not moved.sell_broken("long", 1, 0)


def test_the_backtest_opens_on_red_only() -> None:
    closes = [100.0, 100.0, 100.0]
    g = _guard(closes)
    g = KeltnerGuard(g.closes, [1, -1, -1], g.line, g.buy, g.sell, g.low, g.high)
    [t] = simulate(_bars(closes), [], RULES, signals_held=[_buy(0, 100), _buy(1, 100)], guard=g)
    assert t.opened_at == T0 + timedelta(hours=1)


def test_the_backtest_keeps_a_dead_position_and_closes_it_back_up_at_the_floor() -> None:
    # $100 at 100 on $10: dead at 2 (97 under the LL at 98, in loss); 99 at 3
    # isn't back up at -0.1% of the margin (-$0.01: 99.99); 4 opens at 100,
    # above it: closed at that open. Its Buy at 4 waits.
    closes = [100.0, 99.0, 97.0, 99.0, 100.0, 100.0]
    g = _guard(closes, lows={1: 98.0})
    signals = [_buy(0, 100), _buy(4, 100), _buy(5, 100)]
    dead, reopened = simulate(_bars(closes), [], RULES, signals_held=signals, guard=g)
    assert (dead.closed_at, dead.exit_reason) == (T0 + timedelta(hours=4), DEAD_EXIT)
    assert dead.close_price == 100.0
    assert reopened.opened_at == T0 + timedelta(hours=5)


def test_the_backtest_passes_the_broken_first_sell() -> None:
    closes = [100.0, 104.0, 105.0, 105.0]
    bars = _bars(closes)
    g = _guard(closes, sell=frozenset({1, 2}))
    exits = [exit_at("long", bars[1], "keltner_sell"), exit_at("long", bars[2], "keltner_sell")]
    [t] = simulate(bars, [], RULES, signals_held=[_buy(0, 100)], exits=exits, guard=g)
    assert (t.closed_at, t.exit_reason) == (bars[2].time, f"{TAKE_PROFIT_EXIT}:keltner_sell")
