"""single papers' settings sweeps: their runs

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-16

`exit_sweep_runs`: each run of a single paper's sweep - its leverage,
stop-loss and take-profit and how its strategy's trades did
(docs/papers.md#stop-loss-and-take-profit). Its status is in `paper_sweeps`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A single paper's sweep has no max margin.
    op.alter_column("paper_sweeps", "max_margin", nullable=True)
    op.create_table(
        "exit_sweep_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "sweep_id",
            sa.Integer(),
            sa.ForeignKey("paper_sweeps.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("leverage", sa.Numeric(), nullable=False),
        sa.Column("stop_loss_pct", sa.Numeric(), nullable=True),
        sa.Column("take_profit_pct", sa.Numeric(), nullable=True),
        *(
            sa.Column(name, sa.Numeric(), nullable=False)
            for name in ("return_pct", "max_drawdown_pct", "train_return_pct", "test_return_pct")
        ),
        *(
            sa.Column(name, sa.Integer(), nullable=False)
            for name in ("trades", "won", "stops", "take_profits", "liquidations")
        ),
    )


def downgrade() -> None:
    op.drop_table("exit_sweep_runs")
    op.execute("DELETE FROM paper_sweeps WHERE max_margin IS NULL")
    op.alter_column("paper_sweeps", "max_margin", nullable=False)
