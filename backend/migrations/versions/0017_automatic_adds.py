"""averaging papers add automatically: drop add_step_pct

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-11

An averaging paper no longer adds at a fixed step: it adds whenever its
margin left falls to half (app/executors/position_management.py).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("papers", "add_step_pct")


def downgrade() -> None:
    op.add_column("papers", sa.Column("add_step_pct", sa.Numeric(), nullable=True))
