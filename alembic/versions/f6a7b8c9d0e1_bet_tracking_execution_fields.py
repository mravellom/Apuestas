"""extend bet_tracking for real execution + bankroll reserved

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-18 21:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # BetTracking: agregar columnas para ciclo de vida de ejecución real.
    # El modelo ya existía para staking pasivo; se extiende para soportar arbs
    # con varios legs, tracking de comisión, y distinción entre cuota detectada
    # vs cuota efectivamente ejecutada.
    op.add_column(
        "bet_tracking",
        sa.Column("arbitrage_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_bet_tracking_arbitrage",
        "bet_tracking",
        "arbitrage_opportunities",
        ["arbitrage_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "bet_tracking",
        sa.Column(
            "status",
            sa.String(20),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "bet_tracking",
        sa.Column("odds_at_detection", sa.Numeric(8, 4), nullable=True),
    )
    op.add_column(
        "bet_tracking",
        sa.Column(
            "commission_pct",
            sa.Numeric(6, 5),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "bet_tracking",
        sa.Column("actual_payout", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "bet_tracking",
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "bet_tracking",
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # placed_at pasa a ser nullable (lo setea el usuario al confirmar que apostó),
    # con la misma semántica. Backfill: los registros existentes ya tienen placed_at
    # con timestamp — no toca nada.
    op.alter_column(
        "bet_tracking",
        "placed_at",
        nullable=True,
        server_default=None,
    )
    # odds_at_placement también nullable — al crear el leg en status=pending aún no
    # se sabe la cuota real a la que el libro lo aceptará.
    op.alter_column(
        "bet_tracking",
        "odds_at_placement",
        nullable=True,
    )

    op.create_index(
        "idx_bet_tracking_status",
        "bet_tracking",
        ["user_id", "status"],
    )
    op.create_index(
        "idx_bet_tracking_arb",
        "bet_tracking",
        ["arbitrage_id"],
    )

    # Bankroll: reserved_amount bloquea capital mientras un leg está pending/placed.
    op.add_column(
        "bankrolls",
        sa.Column(
            "reserved_amount",
            sa.Numeric(12, 2),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("bankrolls", "reserved_amount")
    op.drop_index("idx_bet_tracking_arb", table_name="bet_tracking")
    op.drop_index("idx_bet_tracking_status", table_name="bet_tracking")
    op.alter_column(
        "bet_tracking",
        "odds_at_placement",
        nullable=False,
    )
    op.alter_column(
        "bet_tracking",
        "placed_at",
        nullable=False,
        server_default=sa.text("now()"),
    )
    op.drop_column("bet_tracking", "created_at")
    op.drop_column("bet_tracking", "confirmed_at")
    op.drop_column("bet_tracking", "actual_payout")
    op.drop_column("bet_tracking", "commission_pct")
    op.drop_column("bet_tracking", "odds_at_detection")
    op.drop_column("bet_tracking", "status")
    op.drop_constraint("fk_bet_tracking_arbitrage", "bet_tracking", type_="foreignkey")
    op.drop_column("bet_tracking", "arbitrage_id")
