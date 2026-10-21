"""reopen in trend

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-21

`papers.reopen_in_trend`: an intraday averaging paper opens a fresh position
at the close of the candle its take-profit hit on while the strategy's trend
lasts (docs/papers.md#averaging-papers). `sweep_runs.reopen`: a sweep's run
in that mode.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "papers",
        sa.Column("reopen_in_trend", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "sweep_runs",
        sa.Column("reopen", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("sweep_runs", "reopen")
    op.drop_column("papers", "reopen_in_trend")
