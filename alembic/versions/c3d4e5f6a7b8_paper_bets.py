"""paper_bets table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-18 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_bets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id", ondelete="SET NULL")),
        sa.Column("arbitrage_id", sa.Integer(), sa.ForeignKey("arbitrage_opportunities.id", ondelete="SET NULL")),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outcome_id", sa.Integer(), sa.ForeignKey("outcomes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bookmaker_id", sa.Integer(), sa.ForeignKey("bookmakers.id"), nullable=False),
        sa.Column("odds_taken", sa.Numeric(8, 4), nullable=False),
        sa.Column("stake_units", sa.Numeric(8, 5), nullable=False),
        sa.Column("ev_at_placement", sa.Numeric(8, 5)),
        sa.Column("placed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("result", sa.String(20), server_default="pending", nullable=False),
        sa.Column("resolved_at", sa.DateTime()),
        sa.Column("profit_units", sa.Numeric(10, 5)),
    )
    op.create_index("idx_paper_result", "paper_bets", ["result"])
    op.create_index("idx_paper_match", "paper_bets", ["match_id"])
    op.create_index("idx_paper_opp", "paper_bets", ["opportunity_id"])
    op.create_index("idx_paper_arb", "paper_bets", ["arbitrage_id"])


def downgrade() -> None:
    op.drop_index("idx_paper_arb", table_name="paper_bets")
    op.drop_index("idx_paper_opp", table_name="paper_bets")
    op.drop_index("idx_paper_match", table_name="paper_bets")
    op.drop_index("idx_paper_result", table_name="paper_bets")
    op.drop_table("paper_bets")
