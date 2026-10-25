"""sweep runs: when the cash ran out

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-25

`sweep_runs.drained_at`: the date a run's cash fell under its initial size -
it stopped trading there (app/backtest/sweep.py drained_at); NULL: never
(and for the runs stored before - re-run the sweep).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sweep_runs", sa.Column("drained_at", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("sweep_runs", "drained_at")
