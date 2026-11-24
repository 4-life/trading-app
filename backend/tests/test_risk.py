"""Pure unit tests, no database."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest.stats import max_drawdown
from app.budget_allocator import paper_budget_from
from app.config import settings
from app.execution_engine.demo import liquidation_due, liquidation_floor, profitability_pct
from app.execution_engine.engine import top_up_amount
from app.executors.position_management import AVERAGE_DOWN, SIGNAL_ADD, STRENGTH_ADD
from app.market_data.shocks import Shock
from app.papers.models import Paper
from app.risk_engine import service
from app.risk_engine.engine import evaluate
from app.risk_engine.models import ProposedOrder
from app.risk_engine.service import loss_limit


def test_paper_budget_keeps_reserve_and_splits_evenly() -> None:
    assert paper_budget_from(Decimal(5000), 3, Decimal("0.1")) == Decimal(1500)
    assert paper_budget_from(Decimal(5000), 0, Decimal("0.1")) == Decimal(0)


def test_liquidation_at_maintenance_margin() -> None:
    # margin 100, size 1, entry 1000: remaining = 100 + (price - 1000)
    args = ("long", Decimal(1000), Decimal(1), Decimal(100))
    maintenance = Decimal("0.2")
    assert not liquidation_due(*args, Decimal(921), maintenance)  # remaining 21
    assert liquidation_due(*args, Decimal(920), maintenance)  # remaining 20
    short_args = ("short", Decimal(1000), Decimal(1), Decimal(100))
    assert liquidation_due(*short_args, Decimal(1080), maintenance)
    assert not liquidation_due(*short_args, Decimal(1000), maintenance)


def test_the_app_closes_before_the_exchange_liquidates() -> None:
    # A x40 short: 3.4935 at 1604.5, $140 of margin, the exchange's
    # maintenance 1.2% - it liquidates near 1625 (remaining ~$68).
    args = ("short", Decimal("1604.5"), Decimal("3.4935"), Decimal(140))
    app, exchange = Decimal("0.2"), Decimal("0.012")
    assert not liquidation_due(*args, Decimal(1620), app, exchange)
    # 1.1x the exchange's maintenance at ~1623.2: closed there, before 1625.
    assert liquidation_due(*args, Decimal(1624), app, exchange)
    # Without it, only at 20% of the margin left (~1636): after the exchange.
    assert not liquidation_due(*args, Decimal(1630), app)


def test_a_position_at_the_max_leverage_keeps_its_room() -> None:
    # A long at the asset's max leverage, x20: 2.244 at 712.804, $79.98 of
    # margin, the exchange's maintenance 3%. At 708.76 ($70.9 left) a 1.5x
    # buffer would close it; 1.1x waits to ~700.3, before the exchange's ~698.1.
    args = ("long", Decimal("712.804"), Decimal("2.244"), Decimal("79.9766088"))
    app, exchange = Decimal("0.2"), Decimal("0.03")
    assert not liquidation_due(*args, Decimal("708.76"), app, exchange)
    assert liquidation_due(*args, Decimal(698), app, exchange)
    floor, why = liquidation_floor(args[2], args[3], Decimal(698), app, exchange)
    assert why == "1.1x the exchange's 3.0% maintenance margin" and floor > Decimal(51)


def test_a_breached_live_position_is_topped_up_while_cash_and_room_last() -> None:
    args = ("long", Decimal("712.804"), Decimal("2.244"), Decimal("79.9766088"))
    initial, price = Decimal("79.9766088"), Decimal(698)
    # Its loss so far, $33.23: moved in from $900 free.
    assert top_up_amount(*args, initial, price, Decimal(900)) == Decimal("33.23")
    assert top_up_amount(*args, initial, price, Decimal(20)) is None  # not enough cash
    # At twice the margin put in already: closed instead.
    full = ("long", args[1], args[2], Decimal(150))
    assert top_up_amount(*full, initial, price, Decimal(900)) is None
    assert top_up_amount(*args, initial, Decimal(720), Decimal(900)) is None  # in profit


def test_profitability_is_return_on_margin() -> None:
    assert profitability_pct(Decimal(30), Decimal(1000)) == Decimal(3)
    assert profitability_pct(Decimal(-5), Decimal(0)) == Decimal(0)


def test_evaluate_caps_position_by_mode_capital() -> None:
    order = ProposedOrder(strategy_id="1", asset="BTC", notional_usd=5000.0)
    result = evaluate(
        order,
        [],
        daily_pnl_usd=0.0,
        current_equity_usd=4000.0,
        peak_equity_usd=4000.0,
        capital_usd=4000.0,
    )
    assert result.approved
    assert result.approved_notional_usd == 800.0  # 20% of 4000


def test_position_cap_is_on_margin_so_leverage_scales_the_position() -> None:
    order = ProposedOrder(strategy_id="1", asset="BTC", notional_usd=11250.0, leverage=10.0)
    result = evaluate(
        order,
        [],
        daily_pnl_usd=0.0,
        current_equity_usd=5000.0,
        peak_equity_usd=5000.0,
        capital_usd=5000.0,
    )
    assert result.approved
    assert result.approved_notional_usd == 10000.0  # margin capped at 20% of 5000 = 1000, x10


def test_correlated_cap_is_on_net_margin(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.risk_engine.limits import check_correlated_exposure
    from app.risk_engine.models import Position

    monkeypatch.setattr(settings, "correlated_asset_groups", [["BTC", "ETH"]])
    # BTC/ETH group, 50% of 5000 = 2500 margin; an existing 10x long uses 2000 of it.
    existing = [Position("2", "ETH", 20000.0, "long", leverage=10.0)]
    order = ProposedOrder("1", "BTC", 10000.0, "long", leverage=10.0)
    assert check_correlated_exposure(order, existing, 5000.0) == 5000.0  # 500 margin left x10
    short = ProposedOrder("1", "BTC", 10000.0, "short", leverage=10.0)
    assert check_correlated_exposure(short, existing, 5000.0) is None  # nets against the long


def test_evaluate_rejects_on_drawdown() -> None:
    order = ProposedOrder(strategy_id="1", asset="BTC", notional_usd=100.0)
    result = evaluate(
        order,
        [],
        daily_pnl_usd=0.0,
        current_equity_usd=800.0,
        peak_equity_usd=1000.0,
        capital_usd=1000.0,
    )
    assert not result.approved


def test_backtest_max_drawdown_compounds_at_leverage() -> None:
    # +10% then -20% (x1): 1.1 -> 0.88, a 20% drop from the peak
    assert max_drawdown([10.0, -20.0], 1) == pytest.approx(-0.2)
    # x3: 1.3 -> 1.3 * 0.4 = 0.52, a 60% drop
    assert max_drawdown([10.0, -20.0], 3) == pytest.approx(-0.6)
    assert max_drawdown([1.0, 2.0], 3) == 0


def test_loss_limit_follows_the_backtest_drawdown() -> None:
    assert loss_limit([], 3) == (Decimal("0.1"), "default")
    # shallow backtest drawdown: the default stays
    assert loss_limit([1.0, -1.0], 3)[0] == Decimal("0.1")
    # 40% drawdown at x1 -> 50% limit
    limit, basis = loss_limit([10.0, -40.0], 1)
    assert limit == pytest.approx(Decimal("0.5")) and "backtest max drawdown 40.0%" in basis
    # never more than the whole budget
    assert loss_limit([10.0, -90.0], 1)[0] == Decimal(1)


def test_a_shock_holds_back_a_signal_add_but_not_a_dip_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    panic = Shock(now - timedelta(minutes=2), now - timedelta(minutes=1), "panic", "market", "")

    async def shocks(asset: str, span: timedelta) -> list[Shock]:
        return [panic]

    async def off() -> bool:
        return False

    async def cash(paper: Paper, margin: Decimal, notional: Decimal) -> Decimal:
        return Decimal(1000)

    monkeypatch.setattr(service, "recent_shocks", shocks)
    monkeypatch.setattr(service, "is_kill_switch_active", off)
    monkeypatch.setattr(service, "_require_cash", cash)
    paper = Paper(
        kind="averaging",
        enabled=True,
        asset="BTC",
        leverage=Decimal(10),
        initial_size_usd=Decimal(10),
        add_leverage=Decimal(3),
        add_size_usd=None,
        max_margin_usd=None,
    )
    for reason in (SIGNAL_ADD, STRENGTH_ADD):
        with pytest.raises(service.ShockHeld):
            asyncio.run(service._size_add(paper, "long", reason))
    notional, _ = asyncio.run(service._size_add(paper, "long", AVERAGE_DOWN))
    assert notional == Decimal(30)
    # A panic doesn't hold back a short's.
    asyncio.run(service._size_add(paper, "short", SIGNAL_ADD))
