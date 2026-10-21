"""compounding papers, sweep batches

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-16

`papers.compound_margin`: an averaging paper's max margin grows with the
realized PnL (docs/papers.md#averaging-papers). `sweep_runs.compound`: a
sweep's run with it on. `sweep_batches`: several papers' sweeps run one
after another (docs/papers.md#settings-sweep).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "papers",
        sa.Column("compound_margin", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "sweep_runs",
        sa.Column("compound", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_table(
        "sweep_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("max_margin", sa.Numeric(), nullable=False),
        sa.Column("paper_ids", ARRAY(sa.Integer()), nullable=False),
        sa.Column("current_paper_id", sa.Integer(), nullable=True),
        sa.Column("papers_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sweep_batches")
    op.drop_column("sweep_runs", "compound")
    op.drop_column("papers", "compound_margin")
