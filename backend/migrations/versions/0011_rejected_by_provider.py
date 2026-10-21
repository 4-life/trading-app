"""trading_decisions.outcome: rejected_by_provider

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-03

A live order the exchange refused or didn't fill (e.g. a coin it doesn't
list) is `rejected_by_provider` instead of `failed`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "outcome IN ('pending', 'approved', 'rejected_by_risk', 'placed', 'failed')"
_NEW = (
    "outcome IN ('pending', 'approved', 'rejected_by_risk', 'placed', 'failed', "
    "'rejected_by_provider')"
)


def upgrade() -> None:
    op.drop_constraint("ck_decisions_outcome", "trading_decisions", type_="check")
    op.create_check_constraint("ck_decisions_outcome", "trading_decisions", _NEW)


def downgrade() -> None:
    op.execute(
        "UPDATE trading_decisions SET outcome = 'failed' WHERE outcome = 'rejected_by_provider'"
    )
    op.drop_constraint("ck_decisions_outcome", "trading_decisions", type_="check")
    op.create_check_constraint("ck_decisions_outcome", "trading_decisions", _OLD)
