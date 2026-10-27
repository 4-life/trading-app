"""Papers - see docs/papers.md. Create, edit (leverage and position
management), switch to live, disable, re-enable, delete; an averaging
paper's settings sweep."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.averaging import backtest_paper as backtest_averaging
from app.backtest.models import OPEN_AT_END, BacktestTrade, SweepBatch
from app.backtest.sweep import SweepError
from app.db import async_session
from app.execution_engine.live import live_client
from app.execution_engine.models import (
    IN_FLIGHT_OUTCOMES,
    EquitySnapshot,
    Order,
    Position,
    TradingDecision,
)
from app.market_data.assets import configured_assets
from app.market_data.limits import all_market_limits, market_limits
from app.papers.models import (
    MARKET,
    POSITION_MANAGEMENT,
    TRADING_KINDS,
    Paper,
)
from app.papers.prep import backtest_of
from app.papers.sweeps import (
    ExitSweepSort,
    SweepBusy,
    SweepNotRunning,
    SweepSort,
    exit_sweep_runs,
    latest_batch,
    latest_sweep,
    running_sweep,
    start_batch,
    start_sweep,
    stop_batch,
    stop_sweep,
    sweep_runs,
)
from app.risk_engine.blocks import block_reason, unblock_paper
from app.system.models import RiskEvent

router = APIRouter()

# both only where the executor trades both (_EXECUTOR_DIRECTIONS).
AVERAGING_DIRECTIONS = ("long", "short", "both")

Executor = Literal["trend", "vwap", "regime", "supertrend"]
_EXECUTOR_DIRECTIONS: dict[str, tuple[str, ...]] = {
    "trend": ("long", "short", "both"),
    "vwap": ("long", "both"),  # docs/vwap-strategy-engine.md
    "supertrend": ("long", "short"),  # no both (docs/supertrend-strategy-engine.md)
    "regime": ("long", "short", "both"),
}
# Executors that can run as a scanner paper (docs/papers.md#kinds).
_SCANNER_EXECUTORS = ("trend",)


class PaperExits(BaseModel):
    """A single paper's own stop-loss and take-profit, shares of the entry
    price (0.02 = 2%), on top of its strategy's exits; null: none
    (docs/papers.md#stop-loss-and-take-profit)."""

    stop_loss_pct: Decimal | None = Field(default=None, gt=0, lt=1)
    price_take_profit_pct: Decimal | None = Field(default=None, gt=0)


def _check_exits(kind: str, exits: PaperExits) -> None:
    """A single paper's only - an averaging paper has its own take-profit and give-up."""
    if kind != "single" and (
        exits.stop_loss_pct is not None or exits.price_take_profit_pct is not None
    ):
        raise HTTPException(
            status_code=422, detail="stop-loss / take-profit are for single papers only"
        )


class PositionManagement(BaseModel):
    """An averaging paper's position management (docs/papers.md#averaging-papers),
    null for the other kinds. Shares are fractions (0.3 = 30%)."""

    initial_size_usd: Decimal | None = Field(default=None, gt=0)
    # At most 5x: higher-leverage adds can't keep the position from a margin call.
    add_leverage: Decimal | None = Field(default=None, gt=0, le=5)
    add_size_usd: Decimal | None = Field(default=None, gt=0)
    max_drawdown_pct: Decimal | None = Field(default=None, gt=0, lt=1)
    take_profit_pct: Decimal | None = Field(default=None, gt=0)
    # Where its backtest starts trading; null = the whole stored history.
    backtest_start: AwareDatetime | None = None
    # The most margin a position may lock at once (e.g. the cash on the exchange).
    max_margin_usd: Decimal | None = Field(default=None, gt=0)
    # Close at the take-profit at once and keep running after it.
    intraday: bool = False
    # The max margin grows with the realized PnL (docs/papers.md#averaging-papers).
    compound_margin: bool = False
    # Intraday: reopen after a take-profit while the strategy's trend lasts.
    reopen_in_trend: bool = False


# An averaging paper's required fields (add_size_usd defaults to initial_size_usd;
# without max_drawdown_pct only the automatic give-up, OUT_OF_MARGIN_EXIT, applies).
_AVERAGING_REQUIRED = (
    "initial_size_usd",
    "add_leverage",
    "take_profit_pct",
)


def _check_management(kind: str, m: PositionManagement) -> None:
    """Required on an averaging paper, not allowed on the other kinds."""
    # intraday / compound_margin / reopen_in_trend: False = unset.
    values = m.model_dump(include=set(POSITION_MANAGEMENT))
    if kind == "averaging":
        missing = [name for name in _AVERAGING_REQUIRED if values[name] is None]
        if missing:
            raise HTTPException(
                status_code=422, detail=f"an averaging paper needs {', '.join(missing)}"
            )
    elif any(value not in (None, False) for value in values.values()):
        raise HTTPException(
            status_code=422, detail="position management is for averaging papers only"
        )


async def _check_leverage(asset: str, leverage: Decimal, add_leverage: Decimal | None) -> None:
    """Neither above the asset's max leverage at the selected provider (once
    market data stored it - docs/market-data.md#market-limits)."""
    limits = await market_limits(asset)
    if limits is None:
        return
    for name, value in (("leverage", leverage), ("add leverage", add_leverage)):
        if value is not None and float(value) > limits.max_leverage:
            detail = f"{asset} max leverage is x{limits.max_leverage:g}: {name} x{value} is over"
            raise HTTPException(status_code=422, detail=detail)


class PaperOut(PositionManagement, PaperExits):
    id: int
    asset: str
    timeframe: str
    leverage: Decimal
    direction: str
    mode: str
    executor: str
    kind: str
    # The scanner that created this paper, if any.
    parent_id: int | None
    # backfilling / backtesting / failed; null = ready (docs/papers.md#preparation).
    prep_status: str | None
    prep_error: str | None
    profitability_demo: Decimal
    profitability_live: Decimal
    # Net % of price (after fees) over its backtest trades; null = no backtest.
    backtest_return_pct: Decimal | None = None
    # An averaging paper's net backtest PnL (USD, after fees) over its closed
    # positions - the chart's net; null for the other kinds or no backtest.
    backtest_net_usd: Decimal | None = None
    enabled: bool
    enabled_at: datetime
    disabled_by: str | None
    disabled_reason: str | None
    # Set while the risk engine blocks new entries for this paper (Redis).
    blocked_reason: str | None = None
    # The asset's max leverage at the selected provider; null: not known yet.
    max_leverage: Decimal | None = None
    # Its maintenance margin there, a share of the notional - an early
    # liquidation moves the add and give-up levels up; null: not known yet.
    maintenance_margin: Decimal | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaperCreate(PositionManagement, PaperExits):
    kind: Literal["single", "scanner", "averaging"] = "single"
    # Required but for a scanner paper, which has none.
    asset: str | None = None
    timeframe: Literal["1m", "5m", "15m", "1h", "4h"]
    leverage: Decimal = Field(default=Decimal("1.0"), gt=0)
    direction: Literal["long", "short", "both"]
    executor: Executor


async def _get(session: AsyncSession, paper_id: int) -> Paper:
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail=f"no paper {paper_id}")
    return paper


async def _has_open_position(session: AsyncSession, paper_id: int) -> bool:
    found = await session.scalar(
        select(Position.id).where(Position.paper_id == paper_id, Position.closed_at.is_(None))
    )
    return found is not None


async def _has_in_flight(session: AsyncSession, paper_id: int) -> bool:
    found = await session.scalar(
        select(TradingDecision.id).where(
            TradingDecision.paper_id == paper_id,
            TradingDecision.outcome.in_(IN_FLIGHT_OUTCOMES),
        )
    )
    return found is not None


async def _require_idle(session: AsyncSession, paper: Paper, action: str) -> None:
    if await _has_open_position(session, paper.id):
        raise HTTPException(status_code=409, detail=f"close the open position before {action}")
    if await _has_in_flight(session, paper.id):
        raise HTTPException(status_code=409, detail=f"an order is in flight - retry {action} later")


async def _backtest_returns(
    session: AsyncSession, paper_id: int | None = None
) -> dict[int, Decimal]:
    """Paper id -> net backtest return (% of price, after fees) of its closed
    trades - an averaging paper's position still open isn't realized."""
    stmt = (
        select(BacktestTrade.paper_id, func.sum(BacktestTrade.return_pct))
        .where(BacktestTrade.exit_reason != OPEN_AT_END)
        .group_by(BacktestTrade.paper_id)
    )
    if paper_id is not None:
        stmt = stmt.where(BacktestTrade.paper_id == paper_id)
    return {pid: Decimal(total) for pid, total in (await session.execute(stmt)).all()}


async def _backtest_nets_usd(session: AsyncSession) -> dict[int, Decimal]:
    """Paper id -> an averaging paper's net backtest PnL (USD, after fees) of
    its closed positions - the other backtests have no USD PnL."""
    stmt = (
        select(BacktestTrade.paper_id, func.sum(BacktestTrade.pnl_usd))
        .where(BacktestTrade.exit_reason != OPEN_AT_END, BacktestTrade.pnl_usd.is_not(None))
        .group_by(BacktestTrade.paper_id)
    )
    return {pid: Decimal(total) for pid, total in (await session.execute(stmt)).all()}


@router.get("/papers", response_model=list[PaperOut])
async def list_papers() -> list[PaperOut]:
    async with async_session() as session:
        rows = (await session.scalars(select(Paper).order_by(Paper.id))).all()
        backtests = await _backtest_returns(session)
        nets_usd = await _backtest_nets_usd(session)
    limits = await all_market_limits()
    out = []
    for p in rows:
        paper = PaperOut.model_validate(p)
        paper.blocked_reason = await block_reason(p.executor, p.id)
        paper.backtest_return_pct = backtests.get(p.id)
        paper.backtest_net_usd = nets_usd.get(p.id)
        limit = limits.get(p.asset or "")
        if limit is not None:
            paper.max_leverage = Decimal(str(limit.max_leverage))
            paper.maintenance_margin = Decimal(str(limit.maintenance_margin))
        out.append(paper)
    return out


@router.post("/papers", response_model=PaperOut, status_code=201)
async def create_paper(payload: PaperCreate) -> PaperOut:
    """A new paper starts in demo and disabled - the owner enables it (after
    its preparation, for a single paper, to look at the backtest first)."""
    if payload.kind == "scanner":
        if payload.executor not in _SCANNER_EXECUTORS:
            allowed = ", ".join(_SCANNER_EXECUTORS)
            raise HTTPException(status_code=422, detail=f"a scanner paper runs: {allowed}")
        payload.asset = MARKET
    elif payload.asset not in await configured_assets():
        raise HTTPException(status_code=422, detail=f"{payload.asset!r} isn't an added asset")
    _check_management(payload.kind, payload)
    _check_exits(payload.kind, payload)
    if payload.kind != "scanner":
        await _check_leverage(payload.asset, payload.leverage, payload.add_leverage)
    # An averaging paper: its strategy's entries in its direction, short too;
    # both - each position the direction of its entry.
    supported = _EXECUTOR_DIRECTIONS[payload.executor]
    directions = (
        tuple(d for d in AVERAGING_DIRECTIONS if d != "both" or d in supported)
        if payload.kind == "averaging"
        else supported
    )
    if payload.direction not in directions:
        allowed = ", ".join(directions)
        raise HTTPException(
            status_code=422, detail=f"{payload.executor} supports direction: {allowed}"
        )
    now = datetime.now(UTC)
    paper = Paper(
        **payload.model_dump(),
        # A paper with an asset is backfilled (and backtested) before it trades.
        prep_status="backfilling" if payload.kind in TRADING_KINDS else None,
        mode="demo",
        profitability_demo=Decimal(0),
        profitability_live=Decimal(0),
        enabled=False,
        disabled_by="owner",
        disabled_reason="new paper - enable it to start",
        enabled_at=now,
        created_at=now,
        updated_at=now,
    )
    async with async_session() as session:
        session.add(paper)
        await session.commit()
    return PaperOut.model_validate(paper)


class PaperUpdate(PositionManagement, PaperExits):
    """Replaces the leverage and, on an averaging paper, its position management."""

    leverage: Decimal = Field(gt=0)


@router.patch("/papers/{paper_id}", response_model=PaperOut)
async def update_paper(paper_id: int, payload: PaperUpdate) -> PaperOut:
    """Takes effect at once - position management on an open position too.
    The leverage only changes without an open position or an order in flight
    (the position was opened at the old one); live, it must be whole. An
    averaging paper's backtest is re-run on the new settings, a single
    paper's when its stop-loss / take-profit changed (its trading doesn't
    pause)."""
    async with async_session() as session:
        paper = await _get(session, paper_id)
        _check_management(paper.kind, payload)
        _check_exits(paper.kind, payload)
        await _check_leverage(paper.asset, payload.leverage, payload.add_leverage)
        if payload.leverage != paper.leverage:
            await _require_idle(session, paper, "changing the leverage")
            if paper.mode == "live" and payload.leverage != int(payload.leverage):
                raise HTTPException(status_code=409, detail="live leverage must be a whole number")
        exits = (paper.stop_loss_pct, paper.price_take_profit_pct)
        for name, value in payload.model_dump().items():
            setattr(paper, name, value)
        paper.updated_at = datetime.now(UTC)
        await session.commit()
    if paper.kind == "averaging" and paper.prep_status is None:
        await backtest_averaging(paper, None)
    elif exits != (paper.stop_loss_pct, paper.price_take_profit_pct) and paper.prep_status is None:
        backtest = backtest_of(paper)
        if backtest is not None:
            await backtest(paper, None)
    return PaperOut.model_validate(paper)


class SweepIn(BaseModel):
    max_leverage: Decimal = Field(gt=0)  # the highest leverage tried (also the asset's max)
    # An averaging paper's budget, instead of its own (required there); a
    # single paper's sweep has none.
    max_margin: Decimal | None = Field(default=None, gt=0)


class PaperSweepOut(BaseModel):
    """A paper's settings sweep (its latest) - docs/papers.md#settings-sweep."""

    id: int
    paper_id: int
    status: Literal["running", "done", "failed", "stopped"]
    max_leverage: Decimal
    max_margin: Decimal | None  # an averaging paper's
    # The period its runs trade over (train before `split`, test after);
    # null until the candles are loaded.
    start: date | None
    split: date | None
    end: date | None
    runs_total: int  # 0 until the candles are loaded
    runs_done: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class SweepRunOut(BaseModel):
    """One run of a sweep: its settings and stats."""

    leverage: float
    add_leverage: float
    initial_size_usd: float
    add_size_usd: float
    take_profit_pct: float  # of the margin, a fraction
    intraday: bool
    reopen: bool  # intraday, reopened after a take-profit while the trend lasts
    compound: bool  # the budget grows with the realized PnL
    total_usd: float  # closed + the position still open at the end
    closed_pnl_usd: float
    open_unrealized_usd: float
    train_pnl_usd: float  # before the sweep's `split`
    test_pnl_usd: float  # after it
    positions: int
    won: int
    give_ups: int
    liquidations: int
    most_margin_usd: float  # the most locked at once
    cash_drawdown_usd: float
    drained_at: date | None  # the cash fell under the initial size: it stopped trading

    model_config = {"from_attributes": True}


@router.post("/papers/{paper_id}/sweep", response_model=PaperSweepOut, status_code=202)
async def start_paper_sweep(paper_id: int, payload: SweepIn) -> PaperSweepOut:
    """Starts an averaging paper's settings sweep in the background, replacing
    its previous one: its executor, timeframe, add leverage, add size and
    give-up fixed, every leverage up to `max_leverage` (and the asset's max)
    x initial size x take-profit x intraday over its last year, `max_margin`
    as the budget. Each run's stats are stored as they finish - read them with
    GET .../sweep/runs. Nothing about the paper changes. `409` while a sweep
    is running (one at a time on the server), `422` for a paper it can't sweep."""
    async with async_session() as session:
        paper = await _get(session, paper_id)
    try:
        max_margin = None if payload.max_margin is None else float(payload.max_margin)
        sweep = await start_sweep(paper, float(payload.max_leverage), max_margin)
    except SweepBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SweepError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PaperSweepOut.model_validate(sweep)


@router.post("/papers/{paper_id}/sweep/stop", response_model=PaperSweepOut)
async def stop_paper_sweep(paper_id: int) -> PaperSweepOut:
    """Stops the paper's running sweep: `stopped`, the runs stored so far
    kept. `409` when it has none running."""
    try:
        sweep = await stop_sweep(paper_id)
    except SweepNotRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PaperSweepOut.model_validate(sweep)


@router.get("/sweeps/running", response_model=PaperSweepOut | None)
async def get_running_sweep() -> PaperSweepOut | None:
    """The sweep running on the server, any paper's (one at a time); null
    when none."""
    sweep = await running_sweep()
    return None if sweep is None else PaperSweepOut.model_validate(sweep)


@router.get("/papers/{paper_id}/sweep", response_model=PaperSweepOut)
async def get_paper_sweep(paper_id: int) -> PaperSweepOut:
    """The paper's sweep (its latest): status and progress. `404` without one."""
    sweep = await latest_sweep(paper_id)
    if sweep is None:
        raise HTTPException(status_code=404, detail="no sweep for this paper yet")
    return PaperSweepOut.model_validate(sweep)


class ExitSweepRunOut(BaseModel):
    """One run of a single paper's sweep: its leverage, stop-loss and
    take-profit (shares of the entry price; null: none) and how its
    strategy's trades did, compounded at that leverage (% of the margin)."""

    leverage: float
    stop_loss_pct: float | None
    take_profit_pct: float | None
    return_pct: float
    max_drawdown_pct: float
    train_return_pct: float  # before the sweep's `split`
    test_return_pct: float  # after it
    trades: int
    won: int
    stops: int  # closed at the stop-loss
    take_profits: int  # closed at the take-profit
    liquidations: int  # the liquidation reached before the stop - the equity gone

    model_config = {"from_attributes": True}


@router.get("/papers/{paper_id}/sweep/exit-runs", response_model=list[ExitSweepRunOut])
async def get_exit_sweep_runs(
    paper_id: int,
    sort: ExitSweepSort = "return_pct",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(default=5, ge=1, le=1000),
) -> list[ExitSweepRunOut]:
    """A single paper's sweep runs stored so far (while it runs: the finished
    ones), sorted by `sort` - any of the stats. `404` without a sweep."""
    sweep = await latest_sweep(paper_id)
    if sweep is None:
        raise HTTPException(status_code=404, detail="no sweep for this paper yet")
    runs = await exit_sweep_runs(sweep.id, sort, order, limit)
    return [ExitSweepRunOut.model_validate(r) for r in runs]


@router.get("/papers/{paper_id}/sweep/runs", response_model=list[SweepRunOut])
async def get_sweep_runs(
    paper_id: int,
    sort: SweepSort = "total_usd",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(default=5, ge=1, le=1000),
    compound: bool = False,
    robust_only: bool = False,
) -> list[SweepRunOut]:
    """The runs of the paper's sweep stored so far (while it runs: the
    finished ones) with compounding on / off, sorted by `sort` - any of the
    stats - the drained and tight ones last (`robust_only`: left out). `404`
    without a sweep."""
    sweep = await latest_sweep(paper_id)
    if sweep is None:
        raise HTTPException(status_code=404, detail="no sweep for this paper yet")
    runs = await sweep_runs(sweep.id, sort, order, limit, compound, sweep.max_margin, robust_only)
    return [SweepRunOut.model_validate(r) for r in runs]


class SweepBatchIn(BaseModel):
    paper_ids: list[int] = Field(min_length=1)  # averaging papers, run in this order
    max_margin: Decimal = Field(gt=0)  # each paper's budget (not shared)


class SweepBatchOut(BaseModel):
    """Several averaging papers' sweeps run one after another - the latest
    batch (docs/papers.md#batch-sweep)."""

    id: int
    status: Literal["running", "done", "failed", "stopped"]
    max_margin: Decimal
    paper_ids: list[int]
    current_paper_id: int | None
    papers_done: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    # The running paper's sweep (its progress); null between papers or when over.
    current: PaperSweepOut | None = None

    model_config = {"from_attributes": True}


async def _batch_out(batch: SweepBatch) -> SweepBatchOut:
    out = SweepBatchOut.model_validate(batch)
    if batch.status == "running" and batch.current_paper_id is not None:
        sweep = await latest_sweep(batch.current_paper_id)
        if sweep is not None and sweep.status == "running":
            out.current = PaperSweepOut.model_validate(sweep)
    return out


@router.post("/sweeps/batch", response_model=SweepBatchOut, status_code=202)
async def start_sweep_batch(payload: SweepBatchIn) -> SweepBatchOut:
    """Starts the averaging papers' sweeps in the background, one after
    another, each on `max_margin` and up to its asset's max leverage -
    replacing their previous sweeps. `409` while a sweep or a batch runs,
    `422` for a paper it can't sweep."""
    try:
        batch = await start_batch(payload.paper_ids, float(payload.max_margin))
    except SweepBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SweepError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await _batch_out(batch)


@router.get("/sweeps/batch", response_model=SweepBatchOut | None)
async def get_sweep_batch() -> SweepBatchOut | None:
    """The latest batch and its progress; null when none ran yet."""
    batch = await latest_batch()
    return None if batch is None else await _batch_out(batch)


@router.post("/sweeps/batch/stop", response_model=SweepBatchOut)
async def stop_sweep_batch() -> SweepBatchOut:
    """Stops the running batch - its running paper's sweep too (the runs so
    far kept). `409` when none runs."""
    try:
        batch = await stop_batch()
    except SweepNotRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await _batch_out(batch)


@router.post("/papers/{paper_id}/live", response_model=PaperOut)
async def switch_to_live(paper_id: int) -> PaperOut:
    """Demo -> live: needs profitability_demo > 0 or a profitable backtest,
    whole-number leverage, an exchange API, no open demo position, no order
    in flight, and no other enabled live paper on the asset. Scanner coins
    go live on their own (app/scanner/service.py)."""
    async with async_session() as session:
        paper = await _get(session, paper_id)
        if paper.mode == "live":
            raise HTTPException(status_code=409, detail="paper is already live")
        if paper.kind == "scanner" or paper.parent_id is not None:
            raise HTTPException(
                status_code=409,
                detail="scanner coins go live on their own once an exchange API is set",
            )
        if not paper.enabled:
            raise HTTPException(status_code=409, detail="paper is disabled")
        backtest = (await _backtest_returns(session, paper.id)).get(paper.id)
        if paper.profitability_demo <= 0 and not (backtest and backtest > 0):
            raise HTTPException(
                status_code=409, detail="needs demo profit above 0% or a profitable backtest"
            )
        if paper.leverage != int(paper.leverage):
            # Hyperliquid only accepts whole-number leverage.
            raise HTTPException(status_code=409, detail="live leverage must be a whole number")
        try:
            client = await live_client()
        except Exception as exc:
            raise HTTPException(
                status_code=409, detail=f"can't connect to the exchange API: {exc}"
            ) from exc
        if client is None:
            raise HTTPException(status_code=409, detail="add an exchange API in settings")
        await _require_idle(session, paper, "switching to live")
        paper.mode = "live"
        paper.updated_at = datetime.now(UTC)
        try:
            await session.commit()
        except IntegrityError as exc:
            raise HTTPException(
                status_code=409, detail=f"{paper.asset} already has a live paper"
            ) from exc
        return PaperOut.model_validate(paper)


@router.post("/papers/{paper_id}/disable", response_model=PaperOut)
async def disable_paper(paper_id: int) -> PaperOut:
    """Disabled papers aren't run by their executor, so the paper must have
    no open position or order in flight."""
    async with async_session() as session:
        paper = await _get(session, paper_id)
        if not paper.enabled:
            raise HTTPException(status_code=409, detail="paper is already disabled")
        await _require_idle(session, paper, "disabling")
        paper.enabled = False
        paper.disabled_by = "owner"
        paper.disabled_reason = "disabled by owner"
        paper.updated_at = datetime.now(UTC)
        await session.commit()
        return PaperOut.model_validate(paper)


@router.post("/papers/{paper_id}/enable", response_model=PaperOut)
async def enable_paper(paper_id: int) -> PaperOut:
    """Re-enables in the paper's current mode. A live paper needs its asset's
    live slot to be free."""
    async with async_session() as session:
        paper = await _get(session, paper_id)
        if paper.enabled:
            raise HTTPException(status_code=409, detail="paper is already enabled")
        now = datetime.now(UTC)
        paper.enabled = True
        paper.enabled_at = now
        paper.disabled_by = None
        paper.disabled_reason = None
        paper.updated_at = now
        try:
            await session.commit()
        except IntegrityError as exc:
            raise HTTPException(
                status_code=409, detail=f"{paper.asset} already has a live paper"
            ) from exc
    await unblock_paper(paper_id)
    return PaperOut.model_validate(paper)


@router.delete("/papers/{paper_id}", status_code=204)
async def delete_paper(paper_id: int) -> None:
    """Only a disabled paper. Deletes its whole history too (positions,
    orders, decisions, equity snapshots, risk events)."""
    async with async_session() as session:
        paper = await _get(session, paper_id)
        if paper.enabled:
            raise HTTPException(status_code=409, detail="disable the paper before deleting it")
        if paper.prep_status in ("backfilling", "backtesting"):
            raise HTTPException(status_code=409, detail=f"paper is {paper.prep_status} - wait")
        await _require_idle(session, paper, "deleting")
        for model in (TradingDecision, Order, Position, EquitySnapshot, RiskEvent):
            await session.execute(delete(model).where(model.paper_id == paper_id))
        await session.execute(delete(Paper).where(Paper.id == paper_id))
        await session.commit()
