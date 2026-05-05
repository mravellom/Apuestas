"""paper_bets.commission_pct snapshot

Revision ID: l2g3h4i5j6k7
Revises: k1f2g3h4i5j6
Create Date: 2026-05-05 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l2g3h4i5j6k7"
down_revision: Union[str, None] = "k1f2g3h4i5j6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "paper_bets",
        sa.Column("commission_pct", sa.Numeric(6, 5), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paper_bets", "commission_pct")
