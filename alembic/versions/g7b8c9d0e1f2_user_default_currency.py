"""add default_currency to user_configs

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-18 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_configs",
        sa.Column(
            "default_currency",
            sa.String(3),
            server_default="USD",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("user_configs", "default_currency")
