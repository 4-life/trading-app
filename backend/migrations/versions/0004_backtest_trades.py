"""backtest_trades (temporary)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01

Simulated High-Low trades over a paper's stored candles, filled by
`python -m app.backtest.highlow` and drawn on the strategy chart. Temporary:
drop it with a later migration once the strategy is evaluated.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "paper_id", sa.Integer(), sa.ForeignKey("papers.id", ondelete="CASCADE"), index=True
        ),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(), nullable=False),
        sa.Column("stop_loss_price", sa.Numeric(), nullable=False),
        sa.Column("half_closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("half_close_price", sa.Numeric(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_price", sa.Numeric(), nullable=False),
        sa.Column("exit_reason", sa.String(), nullable=False),
        sa.Column("return_pct", sa.Numeric(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("backtest_trades")
