"""paper preparation status

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-02

A new paper is backfilled (and backtested, if its executor has one) before
it trades: papers.prep_status backfilling -> backtesting -> NULL (ready), or
failed with papers.prep_error.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("prep_status", sa.String(), nullable=True))
    op.add_column("papers", sa.Column("prep_error", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_papers_prep_status",
        "papers",
        "prep_status IS NULL OR prep_status IN ('backfilling', 'backtesting', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_papers_prep_status", "papers", type_="check")
    op.drop_column("papers", "prep_error")
    op.drop_column("papers", "prep_status")
