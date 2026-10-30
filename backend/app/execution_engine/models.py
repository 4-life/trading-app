from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The demo mode's balance at start and after a demo reset (docs/papers.md).
DEMO_STARTING_BALANCE_USD = Decimal("5000")


class DemoBalance(Base):
    """The demo mode's simulated balance - a single row (id = 1), $5000 at
    start and after a demo reset. Live balance is read from Hyperliquid, not
    stored."""

    __tablename__ = "demo_balance"
    __table_args__ = (CheckConstraint("id = 1", name="ck_demo_balance_single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    balance_usd: Mapped[Decimal] = mapped_column(Numeric)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Position(Base):
    """Open and closed positions of every paper, both modes. A position is
    open while `closed_at` is null; a paper has at most one open position."""

    __tablename__ = "positions"
    __table_args__ = (
        CheckConstraint("mode IN ('demo', 'live')", name="ck_positions_mode"),
        CheckConstraint("direction IN ('long', 'short')", name="ck_positions_direction"),
        Index(
            "uq_positions_open_paper",
            "paper_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
        Index("ix_positions_mode_closed_at", "mode", "closed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    mode: Mapped[str] = mapped_column(String)
    asset: Mapped[str] = mapped_column(String, index=True)
    direction: Mapped[str] = mapped_column(String)
    size: Mapped[Decimal] = mapped_column(Numeric)
    entry_price: Mapped[Decimal] = mapped_column(Numeric)
    leverage: Mapped[Decimal] = mapped_column(Numeric)
    # Margin still reserved - released on close, never recomputed from the
    # current leverage. A partial close releases (and removes) its share.
    margin_usd: Mapped[Decimal] = mapped_column(Numeric)
    # Margin reserved at open; profitability divides by this.
    initial_margin_usd: Mapped[Decimal] = mapped_column(Numeric)
    # Most favorable price since entry (highest for long, lowest for short).
    peak_price: Mapped[Decimal] = mapped_column(Numeric)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    realized_pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # A dead averaging position (app/executors/keltner_averaging.py): since
    # when it closes once its PnL is back up at DEAD_CLOSE_PNL.
    dead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("mode IN ('demo', 'live')", name="ck_orders_mode"),
        CheckConstraint("side IN ('buy', 'sell')", name="ck_orders_side"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id"), nullable=True, index=True
    )
    mode: Mapped[str] = mapped_column(String)
    asset: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)
    size: Mapped[Decimal] = mapped_column(Numeric)
    fill_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    fee_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    # Hyperliquid's order id - null for demo orders.
    exchange_order_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


OUTCOMES = (
    "pending",
    "approved",
    "rejected_by_risk",
    "placed",
    "failed",
    "rejected_by_provider",
)
IN_FLIGHT_OUTCOMES = ("pending", "approved")


class TradingDecision(Base):
    """docs/postgres.md#trading-decision-log - every entry/exit decision of
    every paper. Also the order queue: an executor inserts a `pending` row,
    the risk engine moves it to `approved` / `rejected_by_risk`, the
    execution engine to `placed` / `failed`. At most one in-flight
    (pending/approved) decision per paper."""

    __tablename__ = "trading_decisions"
    __table_args__ = (
        CheckConstraint("mode IN ('demo', 'live')", name="ck_decisions_mode"),
        CheckConstraint("signal IN ('enter', 'exit', 'add')", name="ck_decisions_signal"),
        CheckConstraint("direction IN ('long', 'short')", name="ck_decisions_direction"),
        CheckConstraint(
            "outcome IN ('pending', 'approved', 'rejected_by_risk', 'placed', 'failed', "
            "'rejected_by_provider')",
            name="ck_decisions_outcome",
        ),
        Index(
            "uq_decisions_in_flight_paper",
            "paper_id",
            unique=True,
            postgresql_where=text("outcome IN ('pending', 'approved')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    mode: Mapped[str] = mapped_column(String, index=True)
    asset: Mapped[str] = mapped_column(String, index=True)

    feature_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # "enter" | "exit" | "add" (a unit added to the open position, averaging down)
    signal: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)  # position direction: "long" | "short"
    # The executor's own reason, e.g. "flat_entry", "stop_loss_2pct".
    reason: Mapped[str] = mapped_column(String)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    # Null until the risk engine decides.
    risk_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    risk_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    position_size_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    stop_loss_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    take_profit_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    # Exits only: share of the open position to close; null = all of it.
    close_fraction: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    outcome: Mapped[str] = mapped_column(String, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)


class EquitySnapshot(Base):
    """Equity curve for the risk engine's drawdown / daily-loss checks. A
    null `paper_id` is the whole mode's equity; otherwise one paper's."""

    __tablename__ = "equity_snapshots"
    __table_args__ = (CheckConstraint("mode IN ('demo', 'live')", name="ck_equity_mode"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String, index=True)
    paper_id: Mapped[int | None] = mapped_column(ForeignKey("papers.id"), nullable=True, index=True)
    equity_usd: Mapped[Decimal] = mapped_column(Numeric)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
