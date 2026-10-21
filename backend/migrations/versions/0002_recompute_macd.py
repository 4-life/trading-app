"""recompute MACD with (2, 15, 21)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30

MACD moved from (12, 26, 9) to (2, 15, 21). Stored readings were computed
with the old periods; delete them so feature-backfill recomputes them (it
fills any timestamp missing a core feature) - older than BACKFILL_DAYS they
are simply gone. Nothing else changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM features WHERE name IN ('macd', 'macd_signal')")


def downgrade() -> None:
    # Not reversible - the old readings are recomputed only by reverting the code.
    pass
