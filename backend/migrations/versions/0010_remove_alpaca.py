"""remove Alpaca and the de-peg guard

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-03

- The reference_prices table (Alpaca NYSE prices) is dropped.
- The stored Alpaca keys are deleted.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM settings WHERE key IN ('alpaca_api_key', 'alpaca_secret_key')")
    op.drop_index("ix_reference_prices_asset_time", table_name="reference_prices")
    op.drop_table("reference_prices")


def downgrade() -> None:
    # The table only - the deleted keys and prices aren't restored.
    op.create_table(
        "reference_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reference_prices_asset_time", "reference_prices", ["asset", "recorded_at"])
