"""averaging papers: the most margin a position may lock

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-12

Adds beyond it are refused live and skipped in the backtest - like a real
account with only so much cash. NULL (every existing paper) = no cap.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("max_margin_usd", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("papers", "max_margin_usd")
