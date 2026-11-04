"""closed_positions: closed positions that outlive their paper

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-04

A closed position's lasting record, without a foreign key to its paper, so
the dashboard's PnL keeps it after the paper is deleted. Filled from the closed
positions there are now; those of papers deleted before this are gone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "closed_positions",
        sa.Column("position_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("size", sa.Numeric(), nullable=False),
        sa.Column("entry_price", sa.Numeric(), nullable=False),
        sa.Column("close_price", sa.Numeric(), nullable=False),
        sa.Column("margin_usd", sa.Numeric(), nullable=False),
        sa.Column("realized_pnl_usd", sa.Numeric(), nullable=False),
        sa.Column("exit_reason", sa.String(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('demo', 'live')", name="ck_closed_positions_mode"),
    )
    op.create_index("ix_closed_positions_mode_closed_at", "closed_positions", ["mode", "closed_at"])
    op.execute(
        """
        INSERT INTO closed_positions (
            position_id, paper_id, mode, asset, direction, size, entry_price, close_price,
            margin_usd, realized_pnl_usd, exit_reason, opened_at, closed_at
        )
        SELECT
            id, paper_id, mode, asset, direction, size, entry_price, COALESCE(close_price, 0),
            initial_margin_usd, COALESCE(realized_pnl_usd, 0), COALESCE(exit_reason, ''),
            opened_at, closed_at
        FROM positions
        WHERE closed_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("closed_positions")
