"""settings sweeps: each averaging paper's latest sweep and its runs

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-15

`paper_sweeps` (its status, progress, period) and `sweep_runs` (each run's
settings and stats, added as they finish) - docs/papers.md#settings-sweep.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_sweeps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "paper_id",
            sa.Integer(),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("max_leverage", sa.Numeric(), nullable=False),
        sa.Column("max_margin", sa.Numeric(), nullable=False),
        sa.Column("start", sa.Date(), nullable=True),
        sa.Column("split", sa.Date(), nullable=True),
        sa.Column("end", sa.Date(), nullable=True),
        sa.Column("runs_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    numeric = [
        "leverage",
        "add_leverage",
        "initial_size_usd",
        "add_size_usd",
        "take_profit_pct",
        "total_usd",
        "closed_pnl_usd",
        "open_unrealized_usd",
        "train_pnl_usd",
        "test_pnl_usd",
        "most_margin_usd",
        "cash_drawdown_usd",
    ]
    op.create_table(
        "sweep_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "sweep_id",
            sa.Integer(),
            sa.ForeignKey("paper_sweeps.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        *(sa.Column(name, sa.Numeric(), nullable=False) for name in numeric),
        sa.Column("intraday", sa.Boolean(), nullable=False),
        *(
            sa.Column(name, sa.Integer(), nullable=False)
            for name in ("positions", "won", "give_ups", "liquidations")
        ),
    )


def downgrade() -> None:
    op.drop_table("sweep_runs")
    op.drop_table("paper_sweeps")
