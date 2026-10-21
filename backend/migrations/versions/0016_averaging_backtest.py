"""averaging backtest: start date, position margin / PnL, fills

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-11

An averaging paper's backtest start (NULL = the whole history), the margin
put in and the PnL of each of its backtest positions, and each position's
buys (the first entry and every add) for the chart. All empty for the
other backtests.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("backtest_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("backtest_trades", sa.Column("margin_usd", sa.Numeric(), nullable=True))
    op.add_column("backtest_trades", sa.Column("pnl_usd", sa.Numeric(), nullable=True))
    op.create_table(
        "backtest_fills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "backtest_trade_id",
            sa.Integer(),
            sa.ForeignKey("backtest_trades.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("margin_usd", sa.Numeric(), nullable=False),
        sa.Column("notional_usd", sa.Numeric(), nullable=False),
    )
    op.create_index("ix_backtest_fills_backtest_trade_id", "backtest_fills", ["backtest_trade_id"])


def downgrade() -> None:
    op.drop_index("ix_backtest_fills_backtest_trade_id", table_name="backtest_fills")
    op.drop_table("backtest_fills")
    op.drop_column("backtest_trades", "pnl_usd")
    op.drop_column("backtest_trades", "margin_usd")
    op.drop_column("papers", "backtest_start")
