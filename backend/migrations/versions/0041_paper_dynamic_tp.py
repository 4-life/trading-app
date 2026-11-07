"""papers: dynamic take-profit

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-07

A Keltner averaging paper's average move from a good entry to a good sell over
the last 30 days, measured once per 24h (app/papers/dynamic_tp.py), for looking at.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("dynamic_tp_move", sa.Numeric(), nullable=True))
    op.add_column("papers", sa.Column("dynamic_tp_cycles", sa.Integer(), nullable=True))
    op.add_column("papers", sa.Column("dynamic_tp_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("papers", "dynamic_tp_at")
    op.drop_column("papers", "dynamic_tp_cycles")
    op.drop_column("papers", "dynamic_tp_move")
