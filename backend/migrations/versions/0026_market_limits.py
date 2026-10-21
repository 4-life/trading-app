"""market limits: each perpetual's max leverage and maintenance margin

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-15

`market_limits` (provider, asset): the most leverage a position may take
and the maintenance margin as a share of the notional - filled by the
market-data service on start (docs/market-data.md#market-limits).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_limits",
        sa.Column("provider", sa.String(), primary_key=True),
        sa.Column("asset", sa.String(), primary_key=True),
        sa.Column("max_leverage", sa.Numeric(), nullable=False),
        sa.Column("maintenance_margin", sa.Numeric(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("market_limits")
