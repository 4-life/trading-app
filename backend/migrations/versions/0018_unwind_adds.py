"""averaging papers: sell the dip adds back at the start price

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-12

An averaging paper's option to sell its dip adds once the price is back at
its first buy's (off for every existing paper), and a side on the
backtest's fills - a sell is such an unwind.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "papers",
        sa.Column("unwind_adds", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "backtest_fills",
        sa.Column("side", sa.String(), nullable=False, server_default="buy"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM backtest_fills WHERE side = 'sell'")
    op.drop_column("backtest_fills", "side")
    op.drop_column("papers", "unwind_adds")
