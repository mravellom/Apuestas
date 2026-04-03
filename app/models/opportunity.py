import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        Index("idx_opportunities_value", "value_pct"),
        Index("idx_opportunities_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    outcome_id: Mapped[int] = mapped_column(ForeignKey("outcomes.id"))
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id"))
    odds_price: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    consensus_prob: Mapped[Decimal] = mapped_column(Numeric(6, 5))
    implied_prob: Mapped[Decimal] = mapped_column(Numeric(6, 5))
    value_pct: Mapped[Decimal] = mapped_column(Numeric(8, 5))
    kelly_stake_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    status: Mapped[str] = mapped_column(String(20), default="active")
    detected_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column()
    closed_at: Mapped[datetime | None] = mapped_column()

    outcome: Mapped["Outcome"] = relationship()
    bookmaker: Mapped["Bookmaker"] = relationship()


class BetTracking(Base):
    __tablename__ = "bet_tracking"
    __table_args__ = (Index("idx_bet_tracking_user", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))
    bankroll_id: Mapped[int] = mapped_column(ForeignKey("bankrolls.id"))
    outcome_id: Mapped[int] = mapped_column(ForeignKey("outcomes.id"))
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id"))
    stake_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    odds_at_placement: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    staking_method: Mapped[str] = mapped_column(String(30))
    result: Mapped[str | None] = mapped_column(String(20))
    profit_loss: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    placed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    settled_at: Mapped[datetime | None] = mapped_column()

    user: Mapped["User"] = relationship()
    opportunity: Mapped["Opportunity | None"] = relationship()
    outcome: Mapped["Outcome"] = relationship()
    bookmaker: Mapped["Bookmaker"] = relationship()
