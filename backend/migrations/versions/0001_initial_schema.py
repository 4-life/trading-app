"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-30

"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Integer(), primary_key=True)


def _ts(name: str, nullable: bool = False) -> sa.Column[Any]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    # --- market data ---
    op.create_table(
        "trades",
        _id(),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("size", sa.Numeric(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        _ts("exchange_timestamp"),
        _ts("collected_at"),
    )
    op.create_index("ix_trades_asset", "trades", ["asset"])
    op.create_index("ix_trades_asset_time", "trades", ["asset", "exchange_timestamp"])

    op.create_table(
        "order_book_snapshots",
        _id(),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("best_bid", sa.Numeric(), nullable=False),
        sa.Column("best_ask", sa.Numeric(), nullable=False),
        sa.Column("bid_depth", sa.Numeric(), nullable=False),
        sa.Column("ask_depth", sa.Numeric(), nullable=False),
        _ts("exchange_timestamp"),
        _ts("collected_at"),
    )
    op.create_index("ix_order_book_snapshots_asset", "order_book_snapshots", ["asset"])
    op.create_index("ix_obs_asset_time", "order_book_snapshots", ["asset", "exchange_timestamp"])

    op.create_table(
        "candles",
        _id(),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("interval", sa.String(), nullable=False),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.Numeric(), nullable=False),
        _ts("open_time"),
    )
    op.create_index("ix_candles_asset", "candles", ["asset"])
    op.create_index(
        "ix_candles_asset_interval_time",
        "candles",
        ["asset", "interval", "open_time"],
        unique=True,
    )

    op.create_table(
        "funding_rates",
        _id(),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("funding_rate", sa.Numeric(), nullable=False),
        sa.Column("premium", sa.Numeric(), nullable=False),
        _ts("exchange_timestamp"),
    )
    op.create_index("ix_funding_rates_asset", "funding_rates", ["asset"])
    op.create_index(
        "ix_funding_asset_time", "funding_rates", ["asset", "exchange_timestamp"], unique=True
    )

    op.create_table(
        "open_interest_snapshots",
        _id(),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("open_interest", sa.Numeric(), nullable=False),
        _ts("collected_at"),
    )
    op.create_index("ix_open_interest_snapshots_asset", "open_interest_snapshots", ["asset"])
    op.create_index("ix_oi_asset_time", "open_interest_snapshots", ["asset", "collected_at"])

    op.create_table(
        "reference_prices",
        _id(),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(), nullable=False),
        _ts("recorded_at"),
    )
    op.create_index("ix_reference_prices_asset_time", "reference_prices", ["asset", "recorded_at"])

    # --- features ---
    op.create_table(
        "features",
        _id(),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("interval", sa.String(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        _ts("computed_at"),
    )
    op.create_index("ix_features_asset", "features", ["asset"])
    op.create_index("ix_features_name", "features", ["name"])
    op.create_index(
        "ix_features_asset_name_interval_time",
        "features",
        ["asset", "name", "interval", "computed_at"],
        unique=True,
    )

    # --- papers ---
    op.create_table(
        "papers",
        _id(),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("leverage", sa.Numeric(), nullable=False, server_default="1.0"),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False, server_default="demo"),
        sa.Column("executor", sa.String(), nullable=False),
        sa.Column("profitability_demo", sa.Numeric(), nullable=False, server_default="0"),
        sa.Column("profitability_live", sa.Numeric(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts("enabled_at"),
        sa.Column("disabled_by", sa.String(), nullable=True),
        sa.Column("disabled_reason", sa.String(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "timeframe IN ('1m', '5m', '15m', '1h', '4h')", name="ck_papers_timeframe"
        ),
        sa.CheckConstraint("direction IN ('long', 'short', 'both')", name="ck_papers_direction"),
        sa.CheckConstraint("mode IN ('demo', 'live')", name="ck_papers_mode"),
        sa.CheckConstraint(
            "disabled_by IS NULL OR disabled_by IN ('owner', 'risk_engine')",
            name="ck_papers_disabled_by",
        ),
        sa.CheckConstraint("leverage > 0", name="ck_papers_leverage"),
    )
    op.create_index("ix_papers_asset", "papers", ["asset"])
    op.create_index("ix_papers_executor", "papers", ["executor"])
    op.create_index(
        "uq_papers_live_asset",
        "papers",
        ["asset"],
        unique=True,
        postgresql_where=sa.text("mode = 'live' AND enabled"),
    )

    # --- execution ---
    op.create_table(
        "demo_balance",
        _id(),
        sa.Column("balance_usd", sa.Numeric(), nullable=False),
        _ts("updated_at"),
        sa.CheckConstraint("id = 1", name="ck_demo_balance_single_row"),
    )
    op.execute("INSERT INTO demo_balance (id, balance_usd, updated_at) VALUES (1, 5000, now())")

    op.create_table(
        "positions",
        _id(),
        sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("size", sa.Numeric(), nullable=False),
        sa.Column("entry_price", sa.Numeric(), nullable=False),
        sa.Column("leverage", sa.Numeric(), nullable=False),
        sa.Column("margin_usd", sa.Numeric(), nullable=False),
        sa.Column("peak_price", sa.Numeric(), nullable=False),
        _ts("opened_at"),
        _ts("closed_at", nullable=True),
        sa.Column("close_price", sa.Numeric(), nullable=True),
        sa.Column("realized_pnl_usd", sa.Numeric(), nullable=True),
        sa.Column("exit_reason", sa.String(), nullable=True),
        sa.CheckConstraint("mode IN ('demo', 'live')", name="ck_positions_mode"),
        sa.CheckConstraint("direction IN ('long', 'short')", name="ck_positions_direction"),
    )
    op.create_index("ix_positions_paper_id", "positions", ["paper_id"])
    op.create_index("ix_positions_asset", "positions", ["asset"])
    op.create_index("ix_positions_mode_closed_at", "positions", ["mode", "closed_at"])
    op.create_index(
        "uq_positions_open_paper",
        "positions",
        ["paper_id"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )

    op.create_table(
        "orders",
        _id(),
        sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("size", sa.Numeric(), nullable=False),
        sa.Column("fill_price", sa.Numeric(), nullable=True),
        sa.Column("fee_usd", sa.Numeric(), nullable=True),
        sa.Column("exchange_order_id", sa.String(), nullable=True, unique=True),
        sa.Column("status", sa.String(), nullable=False),
        _ts("created_at"),
        sa.CheckConstraint("mode IN ('demo', 'live')", name="ck_orders_mode"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_orders_side"),
    )
    op.create_index("ix_orders_paper_id", "orders", ["paper_id"])
    op.create_index("ix_orders_position_id", "orders", ["position_id"])
    op.create_index("ix_orders_asset", "orders", ["asset"])

    op.create_table(
        "trading_decisions",
        _id(),
        _ts("decided_at"),
        sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("feature_snapshot", JSONB(), nullable=False),
        sa.Column("signal", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(), nullable=True),
        sa.Column("risk_approved", sa.Boolean(), nullable=True),
        sa.Column("risk_reason", sa.String(), nullable=True),
        sa.Column("position_size_usd", sa.Numeric(), nullable=True),
        sa.Column("entry_price", sa.Numeric(), nullable=True),
        sa.Column("stop_loss_price", sa.Numeric(), nullable=True),
        sa.Column("take_profit_price", sa.Numeric(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
        sa.CheckConstraint("mode IN ('demo', 'live')", name="ck_decisions_mode"),
        sa.CheckConstraint("signal IN ('enter', 'exit')", name="ck_decisions_signal"),
        sa.CheckConstraint("direction IN ('long', 'short')", name="ck_decisions_direction"),
        sa.CheckConstraint(
            "outcome IN ('pending', 'approved', 'rejected_by_risk', 'placed', 'failed')",
            name="ck_decisions_outcome",
        ),
    )
    op.create_index("ix_trading_decisions_decided_at", "trading_decisions", ["decided_at"])
    op.create_index("ix_trading_decisions_paper_id", "trading_decisions", ["paper_id"])
    op.create_index("ix_trading_decisions_mode", "trading_decisions", ["mode"])
    op.create_index("ix_trading_decisions_asset", "trading_decisions", ["asset"])
    op.create_index("ix_trading_decisions_outcome", "trading_decisions", ["outcome"])
    op.create_index("ix_trading_decisions_order_id", "trading_decisions", ["order_id"])
    op.create_index(
        "uq_decisions_in_flight_paper",
        "trading_decisions",
        ["paper_id"],
        unique=True,
        postgresql_where=sa.text("outcome IN ('pending', 'approved')"),
    )

    op.create_table(
        "equity_snapshots",
        _id(),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id"), nullable=True),
        sa.Column("equity_usd", sa.Numeric(), nullable=False),
        _ts("recorded_at"),
        sa.CheckConstraint("mode IN ('demo', 'live')", name="ck_equity_mode"),
    )
    op.create_index("ix_equity_snapshots_mode", "equity_snapshots", ["mode"])
    op.create_index("ix_equity_snapshots_paper_id", "equity_snapshots", ["paper_id"])
    op.create_index("ix_equity_snapshots_recorded_at", "equity_snapshots", ["recorded_at"])

    # --- strategy state ---
    op.create_table(
        "vortex_regime_log",
        _id(),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("regime", sa.String(), nullable=False),
        _ts("reading_at"),
        _ts("decided_at"),
        sa.CheckConstraint("regime IN ('bull', 'bear', 'flat')", name="ck_vortex_regime"),
    )
    op.create_index(
        "uq_vortex_regime_log_asset_tf_reading",
        "vortex_regime_log",
        ["asset", "timeframe", "reading_at"],
        unique=True,
    )

    # --- system ---
    op.create_table(
        "settings",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("encrypted", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts("updated_at"),
    )

    op.create_table(
        "risk_events",
        _id(),
        _ts("occurred_at"),
        sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id"), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
    )
    op.create_index("ix_risk_events_occurred_at", "risk_events", ["occurred_at"])
    op.create_index("ix_risk_events_paper_id", "risk_events", ["paper_id"])

    op.create_table(
        "system_events",
        _id(),
        _ts("occurred_at"),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
    )
    op.create_index("ix_system_events_occurred_at", "system_events", ["occurred_at"])


def downgrade() -> None:
    for table in (
        "system_events",
        "risk_events",
        "settings",
        "vortex_regime_log",
        "equity_snapshots",
        "trading_decisions",
        "orders",
        "positions",
        "demo_balance",
        "papers",
        "features",
        "reference_prices",
        "open_interest_snapshots",
        "funding_rates",
        "candles",
        "order_book_snapshots",
        "trades",
    ):
        op.drop_table(table)
