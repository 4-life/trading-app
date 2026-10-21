"""partial exits

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01

- trading_decisions.close_fraction: share of the open position an exit
  closes (null = all of it).
- positions.initial_margin_usd: the margin reserved at open. margin_usd
  shrinks with partial closes; profitability divides by this instead.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trading_decisions", sa.Column("close_fraction", sa.Numeric(), nullable=True))
    op.add_column("positions", sa.Column("initial_margin_usd", sa.Numeric(), nullable=True))
    # Live partial fills used to shrink margin_usd too - the best value left
    # for old rows is the current one.
    op.execute("UPDATE positions SET initial_margin_usd = margin_usd")
    op.alter_column("positions", "initial_margin_usd", nullable=False)


def downgrade() -> None:
    op.drop_column("positions", "initial_margin_usd")
    op.drop_column("trading_decisions", "close_fraction")
