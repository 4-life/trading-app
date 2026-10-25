"""drop averaging hedge papers

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-25

The `averaging_hedge` kind is gone: its papers (backtest only - they never
traded) are deleted with their whole history, the kind dropped from
`ck_papers_kind`, and `backtest_trades.hedge_pnl_usd` dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HEDGE_PAPERS = "(SELECT id FROM papers WHERE kind = 'averaging_hedge')"


def upgrade() -> None:
    tables = (
        "backtest_trades",
        "trading_decisions",
        "orders",
        "positions",
        "equity_snapshots",
        "risk_events",
    )
    for table in tables:
        op.execute(f"DELETE FROM {table} WHERE paper_id IN {_HEDGE_PAPERS}")
    op.execute("DELETE FROM papers WHERE kind = 'averaging_hedge'")
    op.drop_constraint("ck_papers_kind", "papers", type_="check")
    op.create_check_constraint(
        "ck_papers_kind", "papers", "kind IN ('single', 'scanner', 'averaging')"
    )
    op.drop_column("backtest_trades", "hedge_pnl_usd")


def downgrade() -> None:
    op.add_column("backtest_trades", sa.Column("hedge_pnl_usd", sa.Numeric(), nullable=True))
    op.drop_constraint("ck_papers_kind", "papers", type_="check")
    op.create_check_constraint(
        "ck_papers_kind", "papers", "kind IN ('single', 'scanner', 'averaging', 'averaging_hedge')"
    )
