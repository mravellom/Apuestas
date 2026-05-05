"""api_usage_log table

Revision ID: k1f2g3h4i5j6
Revises: j0e1f2g3h4i5
Create Date: 2026-05-05 21:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k1f2g3h4i5j6"
down_revision: Union[str, None] = "j0e1f2g3h4i5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_usage_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("sport_key", sa.String(length=100), nullable=True),
        sa.Column("endpoint", sa.String(length=50), nullable=False),
        sa.Column("requests_remaining", sa.Integer(), nullable=True),
        sa.Column("requests_used", sa.Integer(), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_api_usage_log_source", "api_usage_log", ["source"])
    op.create_index("ix_api_usage_log_captured_at", "api_usage_log", ["captured_at"])


def downgrade() -> None:
    op.drop_index("ix_api_usage_log_captured_at", table_name="api_usage_log")
    op.drop_index("ix_api_usage_log_source", table_name="api_usage_log")
    op.drop_table("api_usage_log")
