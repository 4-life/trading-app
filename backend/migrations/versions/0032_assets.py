"""assets

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-25

`assets`: the perpetuals collected live, edited in the dashboard - no longer
the ASSETS env variable (docs/market-data.md#asset-universe). Seeded with the
list in use, so none is lost: ASSETS if it's still set, else the assets
collected live (the order-book snapshots - the WebSocket subscribes to ASSETS
only), else BTC, ETH, SOL (ASSETS' default in the deploy); and every paper's
own asset.
"""

import json
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT = ["BTC", "ETH", "SOL"]


def _env_assets() -> list[str] | None:
    try:
        parsed = json.loads(os.environ.get("ASSETS", ""))
    except ValueError:
        return None
    return [str(a) for a in parsed] if isinstance(parsed, list) else None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("symbol", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    bind = op.get_bind()
    collected = bind.scalars(sa.text("SELECT DISTINCT asset FROM order_book_snapshots")).all()
    in_use = _env_assets() or list(collected) or _DEFAULT
    # A scanner's own coins (its children) stay outside the list, as before.
    papers = bind.scalars(
        sa.text("SELECT DISTINCT asset FROM papers WHERE kind <> 'scanner' AND parent_id IS NULL")
    ).all()
    symbols = sorted(set(in_use) | set(papers))
    if symbols:
        bind.execute(
            sa.text("INSERT INTO assets (symbol, created_at) VALUES (:symbol, now())"),
            [{"symbol": s} for s in symbols],
        )


def downgrade() -> None:
    op.drop_table("assets")
