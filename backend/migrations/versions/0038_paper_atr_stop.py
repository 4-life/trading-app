"""papers: atr_stop

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-02

`papers.atr_stop`: an averaging paper closes once a candle closes at or
beyond the ATR stop line of its position's entry candle
(app/executors/atr_stop.py). The Keltner averaging papers had it always on:
kept on.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "papers",
        sa.Column("atr_stop", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.execute(
        "UPDATE papers SET atr_stop = true WHERE kind = 'averaging' AND executor = 'keltner'"
    )


def downgrade() -> None:
    op.drop_column("papers", "atr_stop")
