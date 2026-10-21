"""remove the High-Low and VWAP strategies, rename vwap_signal to vwap

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-14

- High-Low and (zone) VWAP papers are deleted with their whole history
  (decisions, orders, positions, equity snapshots, risk events; backtest
  rows cascade).
- The VWAP signal papers become `vwap` papers - the strategy now named so.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REMOVED_PAPERS = "SELECT id FROM papers WHERE executor IN ('highlow', 'vwap')"


def upgrade() -> None:
    # FK order: decisions -> orders -> positions (as the paper delete API does).
    for table in ("trading_decisions", "orders", "positions", "equity_snapshots", "risk_events"):
        op.execute(f"DELETE FROM {table} WHERE paper_id IN ({_REMOVED_PAPERS})")
    op.execute("DELETE FROM papers WHERE executor IN ('highlow', 'vwap')")
    op.execute("UPDATE papers SET executor = 'vwap' WHERE executor = 'vwap_signal'")


def downgrade() -> None:
    # Deleted papers aren't restored.
    op.execute("UPDATE papers SET executor = 'vwap_signal' WHERE executor = 'vwap'")
