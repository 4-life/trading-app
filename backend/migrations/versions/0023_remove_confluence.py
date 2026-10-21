"""remove the Confluence strategy

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-14

Confluence papers are deleted with their whole history (decisions, orders,
positions, equity snapshots, risk events; backtest rows cascade).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONFLUENCE_PAPERS = "SELECT id FROM papers WHERE executor = 'confluence'"


def upgrade() -> None:
    # FK order: decisions -> orders -> positions (as the paper delete API does).
    for table in ("trading_decisions", "orders", "positions", "equity_snapshots", "risk_events"):
        op.execute(f"DELETE FROM {table} WHERE paper_id IN ({_CONFLUENCE_PAPERS})")
    op.execute("DELETE FROM papers WHERE executor = 'confluence'")


def downgrade() -> None:
    # Deleted papers aren't restored.
    pass
