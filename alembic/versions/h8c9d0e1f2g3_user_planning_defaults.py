"""planner defaults in user_configs

Revision ID: h8c9d0e1f2g3
Revises: g7b8c9d0e1f2
Create Date: 2026-04-19 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8c9d0e1f2g3"
down_revision: Union[str, None] = "g7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_configs",
        sa.Column(
            "default_daily_target_pct",
            sa.Numeric(5, 3),
            server_default="1.000",
            nullable=False,
        ),
    )
    op.add_column(
        "user_configs",
        sa.Column(
            "default_max_stake_per_arb_pct",
            sa.Numeric(5, 3),
            server_default="15.000",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("user_configs", "default_max_stake_per_arb_pct")
    op.drop_column("user_configs", "default_daily_target_pct")
