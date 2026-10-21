"""averaging papers: a third paper kind for position management

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-11

Position management (0014) becomes its own kind, `averaging`: required
there, NULL on single and scanner papers. A single paper already set up to
average down becomes an averaging paper; the fields are cleared on the rest.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    "initial_size_usd",
    "add_step_pct",
    "add_leverage",
    "add_size_usd",
    "max_drawdown_pct",
    "take_profit_pct",
)


def upgrade() -> None:
    op.drop_constraint("ck_papers_kind", "papers", type_="check")
    op.create_check_constraint(
        "ck_papers_kind", "papers", "kind IN ('single', 'scanner', 'averaging')"
    )
    op.execute(
        "UPDATE papers SET kind = 'averaging' "
        "WHERE kind = 'single' AND add_step_pct IS NOT NULL "
        "AND initial_size_usd IS NOT NULL AND add_leverage IS NOT NULL"
    )
    cleared = ", ".join(f"{name} = NULL" for name in COLUMNS)
    op.execute(f"UPDATE papers SET {cleared} WHERE kind <> 'averaging'")


def downgrade() -> None:
    op.execute("UPDATE papers SET kind = 'single' WHERE kind = 'averaging'")
    op.drop_constraint("ck_papers_kind", "papers", type_="check")
    op.create_check_constraint("ck_papers_kind", "papers", "kind IN ('single', 'scanner')")
