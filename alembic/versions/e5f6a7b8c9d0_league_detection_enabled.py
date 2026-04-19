"""add detection_enabled flag to leagues

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-18 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leagues",
        sa.Column(
            "detection_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    # Backfill: ligas marcadas como solo-monitoreo en el seed actual.
    # Quedan en DB pero no entran al pipeline de value/arbitrage hasta que ROI/latencia lo justifiquen.
    op.execute(
        "UPDATE leagues SET detection_enabled = false "
        "WHERE key IN ('basketball_nba', 'americanfootball_nfl', 'icehockey_nhl')"
    )


def downgrade() -> None:
    op.drop_column("leagues", "detection_enabled")
