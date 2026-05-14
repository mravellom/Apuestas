"""arbitrage_opportunities last_revalidate snapshot

Revision ID: m3h4i5j6k7l8
Revises: l2g3h4i5j6k7
Create Date: 2026-05-13 19:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m3h4i5j6k7l8"
down_revision: Union[str, None] = "l2g3h4i5j6k7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "arbitrage_opportunities",
        sa.Column("last_revalidate_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "arbitrage_opportunities",
        sa.Column("last_revalidate_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "arbitrage_opportunities",
        sa.Column("last_revalidate_profit_pct", sa.Numeric(6, 3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("arbitrage_opportunities", "last_revalidate_profit_pct")
    op.drop_column("arbitrage_opportunities", "last_revalidate_status")
    op.drop_column("arbitrage_opportunities", "last_revalidate_at")
