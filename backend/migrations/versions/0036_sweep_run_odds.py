"""sweep runs: their odds

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-27

`sweep_runs.give_up_probability` (the share of the strategy's entries that
went past the run's survivable move within 7 days), `expected_pnl_usd` (per
position) and `ruin_probability` (its cash running out) - app/backtest/sweep.py
_odds. NULL for the runs stored before - re-run the sweep.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("give_up_probability", "expected_pnl_usd", "ruin_probability")


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("sweep_runs", sa.Column(name, sa.Numeric(), nullable=True))


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("sweep_runs", name)
