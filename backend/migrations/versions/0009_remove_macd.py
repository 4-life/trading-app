"""remove the MACD strategy

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-03

- MACD papers are deleted with their whole history (decisions, orders,
  positions, equity snapshots, risk events; backtest rows cascade).
- The MACD readings (macd / macd_signal) are deleted.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MACD_PAPERS = "SELECT id FROM papers WHERE executor = 'macd'"


def upgrade() -> None:
    # FK order: decisions -> orders -> positions (as the paper delete API does).
    for table in ("trading_decisions", "orders", "positions", "equity_snapshots", "risk_events"):
        op.execute(f"DELETE FROM {table} WHERE paper_id IN ({_MACD_PAPERS})")
    op.execute("DELETE FROM papers WHERE executor = 'macd'")
    op.execute("DELETE FROM features WHERE name IN ('macd', 'macd_signal')")


def downgrade() -> None:
    # Deleted papers and readings aren't restored.
    pass
