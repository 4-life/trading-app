"""wipe market data collected from Lighter testnet

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-03

Testnet support was dropped (mainnet only). The stored market data mixes
Lighter testnet candles (sparse, flat - one trade every few minutes) with
real ones, so it's all deleted: candles, features, funding, trades, order
book snapshots, open interest, backtest trades. New papers backfill (and
backtest) again from the selected provider's mainnet.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "TRUNCATE candles, features, funding_rates, trades, order_book_snapshots, "
        "open_interest_snapshots, backtest_trades"
    )


def downgrade() -> None:
    # Deleted data isn't restored.
    pass
