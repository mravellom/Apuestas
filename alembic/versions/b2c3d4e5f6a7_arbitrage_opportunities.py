"""arbitrage_opportunities table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-16 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "arbitrage_opportunities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "match_id",
            sa.Integer(),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "market_id",
            sa.Integer(),
            sa.ForeignKey("markets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("total_implied", sa.Numeric(8, 6), nullable=False),
        sa.Column("profit_pct", sa.Numeric(6, 3), nullable=False),
        sa.Column("num_outcomes", sa.Integer(), nullable=False),
        sa.Column("legs", sa.JSON(), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active"
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_arb_status", "arbitrage_opportunities", ["status"])
    op.create_index("idx_arb_profit", "arbitrage_opportunities", ["profit_pct"])
    op.create_index(
        "idx_arb_match_market",
        "arbitrage_opportunities",
        ["match_id", "market_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_arb_match_market", table_name="arbitrage_opportunities")
    op.drop_index("idx_arb_profit", table_name="arbitrage_opportunities")
    op.drop_index("idx_arb_status", table_name="arbitrage_opportunities")
    op.drop_table("arbitrage_opportunities")
