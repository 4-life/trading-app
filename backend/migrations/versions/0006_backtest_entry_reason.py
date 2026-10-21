"""backtest_trades.entry_reason

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-02

Why a simulated trade opened (e.g. green_swing, stop_reentry) - shown on the
strategy chart next to its exit reason.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("backtest_trades", sa.Column("entry_reason", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("backtest_trades", "entry_reason")
