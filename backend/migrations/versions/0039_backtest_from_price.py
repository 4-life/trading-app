"""papers, paper_sweeps: where a backtest and a sweep started by price

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-04

A backtest and a sweep start where the current price first appears in the
history (app/backtest/bars.py find_backtest_from): `papers.backtest_from` /
`backtest_from_price` and `paper_sweeps.start_price` record what each used.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("backtest_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("papers", sa.Column("backtest_from_price", sa.Numeric(), nullable=True))
    op.add_column("paper_sweeps", sa.Column("start_price", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("paper_sweeps", "start_price")
    op.drop_column("papers", "backtest_from_price")
    op.drop_column("papers", "backtest_from")
