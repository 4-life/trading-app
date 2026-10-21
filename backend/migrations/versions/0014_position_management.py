"""paper position management: fixed entry size, averaging down, TP, max drawdown

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-11

Optional per-paper parameters (NULL = the executor's own behaviour, so
existing papers are unchanged) and the order queue's `add` signal - a unit
added to the open position.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
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
    for name in COLUMNS:
        op.add_column("papers", sa.Column(name, sa.Numeric(), nullable=True))
    op.drop_constraint("ck_decisions_signal", "trading_decisions", type_="check")
    op.create_check_constraint(
        "ck_decisions_signal", "trading_decisions", "signal IN ('enter', 'exit', 'add')"
    )


def downgrade() -> None:
    # `add` rows can't stay under the old constraint.
    op.execute("DELETE FROM trading_decisions WHERE signal = 'add'")
    op.drop_constraint("ck_decisions_signal", "trading_decisions", type_="check")
    op.create_check_constraint(
        "ck_decisions_signal", "trading_decisions", "signal IN ('enter', 'exit')"
    )
    for name in reversed(COLUMNS):
        op.drop_column("papers", name)
