"""sweeps: the survivable move and the asset's adverse move

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-27

`sweep_runs.survivable_move_pct`: how far the price can move against a run's
first entry before it gives up; `paper_sweeps.adverse_move_pct`: the asset's
95th-percentile move against the strategy's entries within 7 days - a run
surviving under 1.5x that is fragile (app/backtest/sweep.py). NULL for the
sweeps stored before - re-run them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sweep_runs", sa.Column("survivable_move_pct", sa.Numeric(), nullable=True))
    op.add_column("paper_sweeps", sa.Column("adverse_move_pct", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("paper_sweeps", "adverse_move_pct")
    op.drop_column("sweep_runs", "survivable_move_pct")
