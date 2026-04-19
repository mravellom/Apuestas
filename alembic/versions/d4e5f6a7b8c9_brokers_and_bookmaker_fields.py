"""brokers table + bookmaker commission/latency fields

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-18 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brokers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("default_commission_pct", sa.Numeric(6, 5), server_default="0", nullable=False),
        sa.Column("typical_latency_ms", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.add_column(
        "bookmakers",
        sa.Column("commission_pct", sa.Numeric(6, 5), server_default="0", nullable=False),
    )
    op.add_column(
        "bookmakers",
        sa.Column("typical_latency_ms", sa.Integer(), server_default="5000", nullable=False),
    )
    op.add_column(
        "bookmakers",
        sa.Column("broker_id", sa.Integer(), sa.ForeignKey("brokers.id", ondelete="SET NULL")),
    )


def downgrade() -> None:
    op.drop_column("bookmakers", "broker_id")
    op.drop_column("bookmakers", "typical_latency_ms")
    op.drop_column("bookmakers", "commission_pct")
    op.drop_table("brokers")
