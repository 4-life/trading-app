"""positions: dead_at

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-30

`positions.dead_at` - since when a Keltner averaging position is dead (a
close beyond the last confirmed LL / HH in loss): it keeps averaging and
closes once its PnL is back up at DEAD_CLOSE_PNL_USD
(app/executors/keltner_averaging.py). NULL: alive.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("dead_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("positions", "dead_at")
