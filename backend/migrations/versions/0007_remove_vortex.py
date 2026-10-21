"""remove the Vortex + Fractal strategy

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-02

- Vortex papers are deleted with their whole history (decisions, orders,
  positions, equity snapshots, risk events; backtest rows cascade).
- The Vortex Indicator readings (vi_plus / vi_minus) are deleted.
- The vortex_regime_log table is dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VORTEX_PAPERS = "SELECT id FROM papers WHERE executor = 'vortex'"


def upgrade() -> None:
    # FK order: decisions -> orders -> positions (as the paper delete API does).
    for table in ("trading_decisions", "orders", "positions", "equity_snapshots", "risk_events"):
        op.execute(f"DELETE FROM {table} WHERE paper_id IN ({_VORTEX_PAPERS})")
    op.execute("DELETE FROM papers WHERE executor = 'vortex'")
    op.execute("DELETE FROM features WHERE name IN ('vi_plus', 'vi_minus')")
    op.drop_index("uq_vortex_regime_log_asset_tf_reading", table_name="vortex_regime_log")
    op.drop_table("vortex_regime_log")


def downgrade() -> None:
    # The table only - deleted papers and readings aren't restored.
    op.create_table(
        "vortex_regime_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("regime", sa.String(), nullable=False),
        sa.Column("reading_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("regime IN ('bull', 'bear', 'flat')", name="ck_vortex_regime"),
    )
    op.create_index(
        "uq_vortex_regime_log_asset_tf_reading",
        "vortex_regime_log",
        ["asset", "timeframe", "reading_at"],
        unique=True,
    )
