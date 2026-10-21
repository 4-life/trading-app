"""scanner papers

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01

- papers.kind: 'single' (one asset, created by the owner) or 'scanner' (no
  asset - finds coins across the market and creates single papers for them).
- papers.parent_id: the scanner that created a single paper.
- papers.disabled_by may be 'scanner' (it disables its flat children).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("kind", sa.String(), nullable=False, server_default="single"))
    op.add_column(
        "papers",
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("papers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_papers_parent_id", "papers", ["parent_id"])
    op.create_check_constraint("ck_papers_kind", "papers", "kind IN ('single', 'scanner')")
    op.drop_constraint("ck_papers_disabled_by", "papers", type_="check")
    op.create_check_constraint(
        "ck_papers_disabled_by",
        "papers",
        "disabled_by IS NULL OR disabled_by IN ('owner', 'risk_engine', 'scanner')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_papers_disabled_by", "papers", type_="check")
    op.create_check_constraint(
        "ck_papers_disabled_by",
        "papers",
        "disabled_by IS NULL OR disabled_by IN ('owner', 'risk_engine')",
    )
    op.drop_constraint("ck_papers_kind", "papers", type_="check")
    op.drop_index("ix_papers_parent_id", "papers")
    op.drop_column("papers", "parent_id")
    op.drop_column("papers", "kind")
