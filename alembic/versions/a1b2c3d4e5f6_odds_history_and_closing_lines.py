"""odds history indexes and closing_lines table

Revision ID: a1b2c3d4e5f6
Revises: 2bde049fbac1
Create Date: 2026-04-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "2bde049fbac1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_odds_outcome_bookmaker_captured",
        "odds",
        ["outcome_id", "bookmaker_id", sa.text("captured_at DESC")],
    )
    op.create_index(
        "idx_odds_bookmaker_captured",
        "odds",
        ["bookmaker_id", sa.text("captured_at DESC")],
    )

    op.create_table(
        "closing_lines",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "outcome_id",
            sa.Integer(),
            sa.ForeignKey("outcomes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bookmaker_id",
            sa.Integer(),
            sa.ForeignKey("bookmakers.id"),
            nullable=False,
        ),
        sa.Column("price", sa.Numeric(8, 4), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("outcome_id", "bookmaker_id", name="uq_closing_outcome_bm"),
    )
    op.create_index(
        "idx_closing_outcome",
        "closing_lines",
        ["outcome_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_closing_outcome", table_name="closing_lines")
    op.drop_table("closing_lines")
    op.drop_index("idx_odds_bookmaker_captured", table_name="odds")
    op.drop_index("idx_odds_outcome_bookmaker_captured", table_name="odds")
