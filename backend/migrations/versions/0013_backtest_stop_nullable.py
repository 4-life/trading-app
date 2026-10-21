"""backtest_trades.stop_loss_price nullable

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-08

The VWAP strategy has no stop-loss, so its backtest trades have none.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("backtest_trades", "stop_loss_price", existing_type=sa.Numeric(), nullable=True)


def downgrade() -> None:
    # Trades without a stop can't stay in a NOT NULL column.
    op.execute("DELETE FROM backtest_trades WHERE stop_loss_price IS NULL")
    op.alter_column(
        "backtest_trades", "stop_loss_price", existing_type=sa.Numeric(), nullable=False
    )
