"""averaging papers: the intraday option

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-12

Close at the take-profit at once and keep running after it, instead of
waiting for the strategy's sell and stopping (off for every existing paper).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "papers", sa.Column("intraday", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.drop_column("papers", "intraday")
