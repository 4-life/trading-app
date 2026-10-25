from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The exit reason of a position still open on the last candle - its result
# isn't realized: left out of the backtest totals.
OPEN_AT_END = "open_at_end"


class BacktestTrade(Base):
    """A simulated trade of a paper with a backtest (temporary -
    docs/vwap-strategy-engine.md#backtest)."""

    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[Decimal] = mapped_column(Numeric)
    # Null for a strategy without a stop-loss (VWAP).
    stop_loss_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    # Unused since the 50% close was dropped - left null; goes with the table.
    half_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    half_close_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    close_price: Mapped[Decimal] = mapped_column(Numeric)
    entry_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    exit_reason: Mapped[str] = mapped_column(String)
    # Net of both taker fees, % of the entry notional (x leverage = % of margin).
    return_pct: Mapped[Decimal] = mapped_column(Numeric)
    # An averaging paper's position (app/backtest/averaging.py): all the margin
    # put in and the PnL net of fees, in USD; NULL for the other backtests.
    margin_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BacktestFill(Base):
    """A fill of an averaging paper's backtest position - a buy (its first
    entry or an add) or a sell (a unit sold) - temporary, like BacktestTrade."""

    __tablename__ = "backtest_fills"

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_trade_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_trades.id", ondelete="CASCADE"), index=True
    )
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[Decimal] = mapped_column(Numeric)
    margin_usd: Mapped[Decimal] = mapped_column(Numeric)  # a sell: the margin released
    notional_usd: Mapped[Decimal] = mapped_column(Numeric)
    side: Mapped[str] = mapped_column(String, default="buy", server_default="buy")
    # A sell: its unit's profit, before fees. NULL otherwise.
    pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)


class PaperSweep(Base):
    """A paper's settings sweep - its latest one only: an averaging paper's
    (app/backtest/sweep.py, its runs SweepRun rows) or a single paper's
    (app/backtest/exit_sweep.py, ExitSweepRun rows) - runs added as they finish."""

    __tablename__ = "paper_sweeps"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String)  # running | done | failed | stopped
    max_leverage: Mapped[Decimal] = mapped_column(Numeric)
    max_margin: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # averaging only
    # The period its runs trade over (train before `split`, test after);
    # NULL until the candles are loaded.
    start: Mapped[date | None] = mapped_column(Date, nullable=True)
    split: Mapped[date | None] = mapped_column(Date, nullable=True)
    end: Mapped[date | None] = mapped_column(Date, nullable=True)
    runs_total: Mapped[int] = mapped_column(Integer, default=0)
    runs_done: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SweepBatch(Base):
    """Several averaging papers' sweeps run one after another, each on the
    same budget (app/papers/sweeps.py) - each paper's runs in its own
    PaperSweep. The latest one only."""

    __tablename__ = "sweep_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String)  # running | done | failed | stopped
    max_margin: Mapped[Decimal] = mapped_column(Numeric)  # each paper's budget
    paper_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer))  # in the order they run
    current_paper_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    papers_done: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SweepRun(Base):
    """One run of a sweep: its settings and stats."""

    __tablename__ = "sweep_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    sweep_id: Mapped[int] = mapped_column(
        ForeignKey("paper_sweeps.id", ondelete="CASCADE"), index=True
    )
    leverage: Mapped[Decimal] = mapped_column(Numeric)
    add_leverage: Mapped[Decimal] = mapped_column(Numeric)
    initial_size_usd: Mapped[Decimal] = mapped_column(Numeric)
    add_size_usd: Mapped[Decimal] = mapped_column(Numeric)
    take_profit_pct: Mapped[Decimal] = mapped_column(Numeric)  # of the margin, a fraction
    intraday: Mapped[bool] = mapped_column(Boolean)
    # Intraday, reopened after a take-profit while the trend lasts (Rules.reopen).
    reopen: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # The budget grows with the realized PnL (Rules.compound); otherwise banked.
    compound: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    total_usd: Mapped[Decimal] = mapped_column(Numeric)  # closed + the open position
    closed_pnl_usd: Mapped[Decimal] = mapped_column(Numeric)
    open_unrealized_usd: Mapped[Decimal] = mapped_column(Numeric)
    train_pnl_usd: Mapped[Decimal] = mapped_column(Numeric)
    test_pnl_usd: Mapped[Decimal] = mapped_column(Numeric)
    positions: Mapped[int] = mapped_column(Integer)
    won: Mapped[int] = mapped_column(Integer)
    give_ups: Mapped[int] = mapped_column(Integer)
    liquidations: Mapped[int] = mapped_column(Integer)
    most_margin_usd: Mapped[Decimal] = mapped_column(Numeric)
    cash_drawdown_usd: Mapped[Decimal] = mapped_column(Numeric)


class ExitSweepRun(Base):
    """One run of a single paper's sweep (app/backtest/exit_sweep.py): its
    leverage, stop-loss and take-profit, and how its strategy's trades did -
    compounded at that leverage, % of the margin."""

    __tablename__ = "exit_sweep_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    sweep_id: Mapped[int] = mapped_column(
        ForeignKey("paper_sweeps.id", ondelete="CASCADE"), index=True
    )
    leverage: Mapped[Decimal] = mapped_column(Numeric)
    stop_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # of price
    take_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)  # of price
    return_pct: Mapped[Decimal] = mapped_column(Numeric)
    max_drawdown_pct: Mapped[Decimal] = mapped_column(Numeric)
    train_return_pct: Mapped[Decimal] = mapped_column(Numeric)
    test_return_pct: Mapped[Decimal] = mapped_column(Numeric)
    trades: Mapped[int] = mapped_column(Integer)
    won: Mapped[int] = mapped_column(Integer)
    stops: Mapped[int] = mapped_column(Integer)
    take_profits: Mapped[int] = mapped_column(Integer)
    liquidations: Mapped[int] = mapped_column(Integer)
