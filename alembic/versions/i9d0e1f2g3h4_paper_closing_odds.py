"""paper_bets.closing_odds for CLV tracking

Revision ID: i9d0e1f2g3h4
Revises: h8c9d0e1f2g3
Create Date: 2026-04-24 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i9d0e1f2g3h4"
down_revision: Union[str, None] = "h8c9d0e1f2g3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Closing line a la que el partido cerró para el mismo (outcome, bookmaker)
    # de la apuesta. Se rellena cuando capture_closing_lines_job corre antes
    # del kickoff. Nullable porque PaperBets antiguas no tienen closing capturado.
    op.add_column(
        "paper_bets",
        sa.Column("closing_odds", sa.Numeric(8, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paper_bets", "closing_odds")
