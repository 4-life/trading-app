"""End-to-end pipeline test, run against the throwaway stack in
docker/test/compose.yaml (docs/testing.md#integration-tests): a fresh
database, real Hyperliquid data, and every layer exercised in order -
paper -> backfill -> features -> executors -> risk engine -> execution
engine -> manual close -> liquidation -> watchdog -> api -> demo reset.

Tests run in file order and share state (the paper, the token): later tests
depend on earlier ones, like the real pipeline. test_demo_reset must stay last.
"""

from decimal import Decimal
from typing import Any

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.config import settings
from app.db import async_session
from app.exchange.hyperliquid import HyperliquidAdapter
from app.execution_engine import engine as execution_engine
from app.execution_engine.demo import Quote
from app.execution_engine.models import (
    DEMO_STARTING_BALANCE_USD,
    DemoBalance,
    Position,
    TradingDecision,
)
from app.executors.base import run_once as run_executor_once
from app.executors.trend import TrendStrategy
from app.executors.vwap import VwapStrategy
from app.feature_engine import backfill as feature_backfill
from app.feature_engine.models import Feature
from app.main import app
from app.market_data import backfill as market_backfill
from app.market_data.models import Candle, FundingRate
from app.order_queue import Direction, Signal, queue_decision
from app.papers.models import Paper
from app.risk_engine.service import RiskEngine
from app.system.exchange_api import DEFAULT_SOURCE
from app.watchdog.engine import run_once as run_watchdog_once
from app.watchdog.redis_client import get_last_check_results, set_kill_switch

ASSET = "BTC"
TIMEFRAME = "15m"
state: dict[str, Any] = {}
_adapter: HyperliquidAdapter | None = None


async def adapter() -> HyperliquidAdapter:
    global _adapter
    if _adapter is None:
        _adapter = HyperliquidAdapter(DEFAULT_SOURCE.url)
        await _adapter.connect(skip_ws=True)
    return _adapter


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {state['token']}"}


async def paper() -> Paper:
    async with async_session() as session:
        found = await session.get(Paper, state["paper_id"])
    assert found is not None
    return found


async def open_position() -> Position | None:
    async with async_session() as session:
        position: Position | None = await session.scalar(
            select(Position).where(
                Position.paper_id == state["paper_id"], Position.closed_at.is_(None)
            )
        )
    return position


async def process_queue() -> None:
    """One risk-engine pass, then one execution-engine pass."""
    await RiskEngine(await adapter()).run_once()
    await execution_engine.run_once(await adapter())


async def test_login_and_create_paper() -> None:
    async with client() as c:
        assert (await c.post("/papers", json={})).status_code == 401
        wrong = await c.post("/login", json={"password": "wrong"})
        assert wrong.status_code == 401
        login = await c.post("/login", json={"password": settings.app_password})
        assert login.status_code == 200
        state["token"] = login.json()["token"]
        # Added already (409) or now.
        added = await c.post("/assets", headers=auth(), json={"symbol": ASSET})
        assert added.status_code in (201, 409), added.text

        created = await c.post(
            "/papers",
            headers=auth(),
            json={
                "asset": ASSET,
                "timeframe": TIMEFRAME,
                "direction": "long",
                "executor": "trend",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["mode"] == "demo" and not body["enabled"]  # new papers start disabled
        state["paper_id"] = body["id"]
        enabled = await c.post(f"/papers/{body['id']}/enable", headers=auth())
        assert enabled.status_code == 200 and enabled.json()["enabled"]

        rejected = await c.post(
            "/papers",
            headers=auth(),
            json={
                "asset": ASSET,
                "timeframe": TIMEFRAME,
                "direction": "short",
                "executor": "vwap",
            },
        )
        assert rejected.status_code == 422  # VWAP: long or both, no short-only


async def test_backfill_seeds_paper_history() -> None:
    await market_backfill.main()
    async with async_session() as session:
        candles = await session.scalar(
            select(func.count(Candle.id)).where(Candle.asset == ASSET, Candle.interval == TIMEFRAME)
        )
        funding = await session.scalar(
            select(func.count(FundingRate.id)).where(FundingRate.asset == ASSET)
        )
    assert candles, "no candles backfilled for the paper's (asset, timeframe)"
    assert funding, "no funding history backfilled"


async def test_feature_backfill_computes_features() -> None:
    await feature_backfill.main()
    async with async_session() as session:
        names = set(
            (
                await session.scalars(
                    select(Feature.name)
                    .where(Feature.asset == ASSET, Feature.interval == TIMEFRAME)
                    .distinct()
                )
            ).all()
        )
    assert {"atr", "momentum"} <= names


async def test_executors_run_a_pass() -> None:
    await set_kill_switch(False)
    await run_executor_once(TrendStrategy())
    await run_executor_once(VwapStrategy())  # no VWAP papers - must not fail


async def test_order_flow_opens_a_position() -> None:
    # Whatever the trend executor queued depends on the market - replace it
    # with a known entry so the rest of the flow is deterministic.
    async with async_session() as session:
        await session.execute(
            delete(TradingDecision).where(
                TradingDecision.paper_id == state["paper_id"],
                TradingDecision.outcome.in_(("pending", "approved")),
            )
        )
        await session.commit()
    decision_id = await queue_decision(await paper(), Signal("enter", "long", "e2e_entry"), None)

    await process_queue()

    async with async_session() as session:
        decision = await session.get(TradingDecision, decision_id)
        balance = await session.get(DemoBalance, 1)
    assert decision is not None
    assert decision.risk_approved, decision.risk_reason
    assert decision.position_size_usd and decision.position_size_usd > 0
    assert decision.outcome == "placed", decision.risk_reason
    position = await open_position()
    assert position is not None and position.direction == "long"
    assert balance is not None and balance.balance_usd < DEMO_STARTING_BALANCE_USD


async def test_portfolio_shows_the_position() -> None:
    async with client() as c:
        response = await c.get("/portfolio?mode=demo", headers=auth())
        live = await c.get("/portfolio?mode=live", headers=auth())
    body = response.json()
    assert body["live_data"] and body["stats"]["open_positions"] == 1
    assert body["open_positions"][0]["paper_id"] == state["paper_id"]
    assert live.json()["live_data"] is False


async def test_partial_close_keeps_the_rest_open() -> None:
    position = await open_position()
    assert position is not None
    direction: Direction = "long" if position.direction == "long" else "short"
    signal = Signal("exit", direction, "e2e_half", close_fraction=Decimal("0.5"))
    await queue_decision(await paper(), signal, None)
    await process_queue()

    half = await open_position()
    assert half is not None and half.id == position.id
    assert half.size == position.size / 2
    assert half.margin_usd == position.margin_usd / 2
    assert half.initial_margin_usd == position.initial_margin_usd
    assert half.realized_pnl_usd is not None


async def test_manual_close_through_the_queue() -> None:
    position = await open_position()
    assert position is not None
    async with client() as c:
        response = await c.post(f"/positions/{position.id}/close", headers=auth())
    assert response.status_code == 200, response.text

    await process_queue()

    async with async_session() as session:
        closed = await session.get(Position, position.id)
    assert closed is not None and closed.closed_at is not None
    assert closed.exit_reason == "manual_close"
    assert closed.realized_pnl_usd is not None
    # Fees alone make the realized PnL non-zero.
    assert (await paper()).profitability_demo != 0


async def test_liquidation_below_maintenance_margin() -> None:
    await queue_decision(await paper(), Signal("enter", "long", "e2e_entry"), None)
    await process_queue()
    position = await open_position()
    assert position is not None

    crash_price = position.entry_price * Decimal("0.5")
    await execution_engine._liquidate(position.id, Quote(crash_price, crash_price), "e2e")

    async with async_session() as session:
        closed = await session.get(Position, position.id)
        logged = await session.scalar(
            select(func.count(TradingDecision.id)).where(
                TradingDecision.paper_id == state["paper_id"],
                TradingDecision.reason == "liquidation",
                TradingDecision.outcome == "placed",
            )
        )
    assert closed is not None and closed.exit_reason == "liquidation"
    assert logged == 1


async def test_watchdog_records_every_check() -> None:
    await run_watchdog_once(await adapter())
    results = await get_last_check_results()
    assert results is not None
    names = {r["name"] for r in results["results"]}
    assert {
        "database",
        "exchange_connectivity",
        "clock_drift",
        "order_rate",
        "position_protection",
        "api",
    } <= names
    async with client() as c:
        health = await c.get("/system-health", headers=auth())
    assert health.status_code == 200 and health.json()["checks"]


async def test_api_endpoints() -> None:
    async with client() as c:
        decisions = (await c.get("/decisions?mode=demo&page_size=2", headers=auth())).json()
        assert decisions["total"] >= 3 and len(decisions["items"]) == 2

        saved = await c.put(
            "/settings", headers=auth(), json={"keys": {"telegram_chat_id": "123456789"}}
        )
        assert saved.status_code == 200, saved.text
        masked = saved.json()["keys"]["telegram_chat_id"]
        assert masked.endswith("6789") and "1234" not in masked
        await c.put("/settings", headers=auth(), json={"keys": {"telegram_chat_id": ""}})

        off = await c.post("/auto-open", headers=auth(), json={"enabled": False})
        assert off.json() == {"enabled": False}
        await c.post("/auto-open", headers=auth(), json={"enabled": True})
        assert (await c.get("/auto-open", headers=auth())).json() == {"enabled": True}


async def test_paper_lifecycle() -> None:
    async with client() as c:
        # Realized PnL is negative (fees, liquidation) - can't go live.
        live = await c.post(f"/papers/{state['paper_id']}/live", headers=auth())
        assert live.status_code == 409

        disabled = await c.post(f"/papers/{state['paper_id']}/disable", headers=auth())
        assert disabled.status_code == 200 and not disabled.json()["enabled"]
        enabled = await c.post(f"/papers/{state['paper_id']}/enable", headers=auth())
        assert enabled.status_code == 200 and enabled.json()["enabled"]

        extra = await c.post(
            "/papers",
            headers=auth(),
            json={"asset": ASSET, "timeframe": "1h", "direction": "both", "executor": "trend"},
        )
        extra_id = extra.json()["id"]
        await c.post(f"/papers/{extra_id}/enable", headers=auth())
        assert (await c.delete(f"/papers/{extra_id}", headers=auth())).status_code == 409
        await c.post(f"/papers/{extra_id}/disable", headers=auth())
        assert (await c.delete(f"/papers/{extra_id}", headers=auth())).status_code == 204


async def test_demo_reset() -> None:
    """Must stay last - wipes the demo state everything above created."""
    async with client() as c:
        response = await c.post("/reset", headers=auth())
    assert response.status_code == 200
    async with async_session() as session:
        positions = await session.scalar(
            select(func.count(Position.id)).where(Position.mode == "demo")
        )
        decisions = await session.scalar(
            select(func.count(TradingDecision.id)).where(TradingDecision.mode == "demo")
        )
        balance = await session.get(DemoBalance, 1)
    assert positions == 0 and decisions == 0
    assert balance is not None and balance.balance_usd == DEMO_STARTING_BALANCE_USD
    assert (await paper()).profitability_demo == 0
