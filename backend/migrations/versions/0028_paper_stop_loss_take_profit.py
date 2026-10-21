"""single papers: a stop-loss and take-profit of their own

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-16

`papers.stop_loss_pct` / `papers.price_take_profit_pct`: a share of the
entry price - exits on top of the strategy's own (NULL: none) -
docs/papers.md#stop-loss-and-take-profit.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("stop_loss_pct", sa.Numeric(), nullable=True))
    op.add_column("papers", sa.Column("price_take_profit_pct", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("papers", "price_take_profit_pct")
    op.drop_column("papers", "stop_loss_pct")
