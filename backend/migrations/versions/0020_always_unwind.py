"""averaging papers always sell their dip units back: drop unwind_adds

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-12

Selling each dip unit at the level of the add above it is no longer an
option - every averaging paper does it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("papers", "unwind_adds")


def downgrade() -> None:
    op.add_column(
        "papers",
        sa.Column("unwind_adds", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
