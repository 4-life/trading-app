"""averaging hedge papers: a fourth paper kind

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-14

- `averaging_hedge`: an averaging long fuelled by a short on ETH - backtest
  only for now (docs/papers.md#averaging-hedge-papers).
- `backtest_fills.pnl_usd`: a sell's unit profit, or the PnL a hedge short's
  reduce / close realized (re-run an averaging backtest to fill it in).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_papers_kind", "papers", type_="check")
    op.create_check_constraint(
        "ck_papers_kind", "papers", "kind IN ('single', 'scanner', 'averaging', 'averaging_hedge')"
    )
    op.add_column("backtest_fills", sa.Column("pnl_usd", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("backtest_fills", "pnl_usd")
    op.execute(
        "DELETE FROM backtest_trades WHERE paper_id IN "
        "(SELECT id FROM papers WHERE kind = 'averaging_hedge')"
    )
    for table in ("trading_decisions", "orders", "positions", "equity_snapshots", "risk_events"):
        op.execute(
            f"DELETE FROM {table} WHERE paper_id IN "
            "(SELECT id FROM papers WHERE kind = 'averaging_hedge')"
        )
    op.execute("DELETE FROM papers WHERE kind = 'averaging_hedge'")
    op.drop_constraint("ck_papers_kind", "papers", type_="check")
    op.create_check_constraint(
        "ck_papers_kind", "papers", "kind IN ('single', 'scanner', 'averaging')"
    )
