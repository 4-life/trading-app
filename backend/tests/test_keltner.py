"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta

from app.backtest import keltner as backtest
from app.backtest.bars import Bar
from app.backtest.models import OPEN_AT_END
from app.executors.keltner import KELTNER_BUY, KELTNER_SELL, decide_signal
from app.executors.keltner_signals import LENGTH, keltner_signals, percent_b

T0 = datetime(2026, 10, 1, tzinfo=UTC)

# A quiet range, a close under the band and back, then a close over it and back.
QUIET = [100.0 + k % 2 for k in range(LENGTH + 6)]
DIP = len(QUIET)
CLOSES = [*QUIET, 95.0, 100.5, *QUIET[:6], 106.0, 100.5, *QUIET[:4]]
SPIKE = DIP + 8


def _signals() -> tuple[list[bool], list[bool]]:
    ks = keltner_signals([c + 0.2 for c in CLOSES], [c - 0.2 for c in CLOSES], CLOSES)
    return ks.buy, ks.sell


def test_percent_b_waits_for_the_band() -> None:
    bbr = percent_b(CLOSES)
    assert bbr[: LENGTH - 1] == [None] * (LENGTH - 1)
    dip, spike = bbr[DIP], bbr[SPIKE]
    assert dip is not None and dip < 0  # under the lower edge
    assert spike is not None and spike > 1  # over the upper edge
    assert percent_b([1.0] * LENGTH)[-1] is None  # a flat band


def test_buy_on_the_close_back_over_the_lower_edge() -> None:
    buy, sell = _signals()
    assert [k for k, b in enumerate(buy) if b] == [DIP + 1]
    assert [k for k, s in enumerate(sell) if s] == [SPIKE + 1]


def test_a_long_paper_buys_on_buy_and_closes_on_sell() -> None:
    buy = decide_signal(None, "long", entered_on_signal=False, paper_direction="long")
    assert buy is not None and (buy.signal, buy.direction, buy.reason) == (
        "enter",
        "long",
        KELTNER_BUY,
    )
    assert decide_signal(None, "long", True, "long") is None  # once per signal
    assert decide_signal(None, "short", False, "long") is None  # a sell opens no short
    sell = decide_signal("long", "short", False, "long")
    assert sell is not None and (sell.signal, sell.direction, sell.reason) == (
        "exit",
        "long",
        KELTNER_SELL,
    )
    assert decide_signal("long", "long", False, "long") is None


def test_a_short_paper_sells_on_sell_and_closes_on_buy() -> None:
    sell = decide_signal(None, "short", False, "short")
    assert sell is not None and (sell.signal, sell.direction) == ("enter", "short")
    assert decide_signal(None, "long", False, "short") is None  # a buy opens no long
    buy = decide_signal("short", "long", False, "short")
    assert buy is not None and (buy.signal, buy.reason) == ("exit", KELTNER_BUY)


def test_both_enters_either_way() -> None:
    for signal in ("long", "short"):
        entry = decide_signal(None, signal, False, "both")
        assert entry is not None and (entry.signal, entry.direction) == ("enter", signal)


def _bars() -> list[Bar]:
    return [Bar(T0 + timedelta(hours=k), c, c + 0.2, c - 0.2, c) for k, c in enumerate(CLOSES)]


def test_backtest_trades_from_signal_to_signal() -> None:
    bars = _bars()
    (long,) = backtest.simulate(bars, "long")
    assert (long.opened_at, long.closed_at, long.exit_reason) == (
        bars[DIP + 1].time,
        bars[SPIKE + 1].time,
        KELTNER_SELL,
    )
    (short,) = backtest.simulate(bars, "short")
    assert (short.opened_at, short.exit_reason) == (bars[SPIKE + 1].time, OPEN_AT_END)
    # Both: the Sell closes the long and opens the short on the same candle.
    both = backtest.simulate(bars, "both")
    assert [(t.direction, t.opened_at) for t in both] == [
        ("long", bars[DIP + 1].time),
        ("short", bars[SPIKE + 1].time),
    ]
