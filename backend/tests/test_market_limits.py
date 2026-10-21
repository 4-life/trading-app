"""Pure unit tests, no database."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from app.api import papers as papers_api
from app.backtest.averaging import Position, rules_of
from app.exchange.lighter import lighter_margin_limits
from app.market_data.limits import Limits
from app.papers.models import Paper

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def test_lighters_margin_fractions_are_basis_points() -> None:
    # SPY and QQQ as Lighter's orderBookDetails gives them.
    spy = {"min_initial_margin_fraction": 200, "maintenance_margin_fraction": 120}
    qqq = {"min_initial_margin_fraction": 333, "maintenance_margin_fraction": 199}
    assert lighter_margin_limits(spy) == (Decimal(50), Decimal("0.012"))
    max_qqq, maintenance_qqq = lighter_margin_limits(qqq)
    assert float(max_qqq) == pytest.approx(30.03, abs=0.01) and maintenance_qqq == Decimal("0.0199")


def test_the_exchange_liquidates_at_its_maintenance_share_of_the_notional() -> None:
    # $2 of margin for $100 at 100 (x50), 1.2% maintenance: liquidated at ~99.19 -
    # 60% of the margin still left, where the old 20%-of-margin rule waited for 98.4.
    pos = Position(T0, "", 100)
    pos.buy(T0, 100, 2, 50, 0.0)
    price = pos.liquidation(0.2, 0.012)
    assert price == pytest.approx(98 / 0.988)
    equity = 2 + (price - 100)
    assert equity == pytest.approx(0.012 * price)
    assert pos.liquidation(0.2) == pytest.approx(98.4)


def _paper(leverage: float, add_leverage: float) -> Paper:
    return Paper(
        asset="SPY",
        leverage=Decimal(str(leverage)),
        add_leverage=Decimal(str(add_leverage)),
        initial_size_usd=Decimal(100),
        take_profit_pct=Decimal("0.2"),
        max_margin_usd=Decimal(1000),
        intraday=False,
    )


def test_the_backtest_caps_the_leverages_at_the_exchanges_max() -> None:
    rules = rules_of(_paper(100, 5), Limits(50, 0.012))
    assert (rules.leverage, rules.add_leverage, rules.maintenance_notional) == (50, 5, 0.012)
    plain = rules_of(_paper(100, 5))
    assert (plain.leverage, plain.maintenance_notional) == (100, None)


def test_the_api_rejects_a_leverage_over_the_assets_max(monkeypatch: pytest.MonkeyPatch) -> None:
    async def limits(_: str) -> Limits:
        return Limits(50, 0.012)

    monkeypatch.setattr(papers_api, "market_limits", limits)

    def check(*args: Any) -> None:
        asyncio.run(papers_api._check_leverage(*args))

    check("SPY", Decimal(50), Decimal(5))
    with pytest.raises(HTTPException) as err:
        check("SPY", Decimal(100), Decimal(5))
    assert err.value.status_code == 422 and "x50" in str(err.value.detail)
    with pytest.raises(HTTPException):
        check("SPY", Decimal(10), Decimal(60))
