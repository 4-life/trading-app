"""averaging hedge papers: the shorts' PnL per backtest position

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-14

`backtest_trades.hedge_pnl_usd`: an averaging hedge position's shorts' part
of `pnl_usd` (re-run its backtest to fill it in).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("backtest_trades", sa.Column("hedge_pnl_usd", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("backtest_trades", "hedge_pnl_usd")
