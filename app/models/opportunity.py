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
    """
    Apuesta real (o intención de apuesta) de un usuario.

    Estados (`status`):
      pending   → creada por el sistema al ejecutar un arb o value bet; capital reservado en bankroll
      placed    → usuario confirmó que colocó la apuesta en el libro (con cuota real)
      confirmed → libro devolvió confirmación (en flujo manual puede saltarse)
      rejected  → libro rechazó o usuario canceló antes de colocar
      void      → partido anulado / apuesta retornada

    Resultado (`result`) se setea al liquidar tras partido completado.
    """
    __tablename__ = "bet_tracking"
    __table_args__ = (
        Index("idx_bet_tracking_user", "user_id"),
        Index("idx_bet_tracking_status", "user_id", "status"),
        Index("idx_bet_tracking_arb", "arbitrage_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))
    arbitrage_id: Mapped[int | None] = mapped_column(
        ForeignKey("arbitrage_opportunities.id", ondelete="SET NULL")
    )
    bankroll_id: Mapped[int] = mapped_column(ForeignKey("bankrolls.id"))
    outcome_id: Mapped[int] = mapped_column(ForeignKey("outcomes.id"))
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id"))
    stake_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Cuota que el motor reportó al detectar. Nullable para compat con registros
    # legados creados antes de este cambio.
    odds_at_detection: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    # Cuota real a la que el libro aceptó la apuesta. Nullable hasta que el
    # usuario confirme el placement.
    odds_at_placement: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    commission_pct: Mapped[Decimal] = mapped_column(Numeric(6, 5), default=Decimal("0"))
    staking_method: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    result: Mapped[str | None] = mapped_column(String(20))
    actual_payout: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    profit_loss: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    placed_at: Mapped[datetime | None] = mapped_column()
    confirmed_at: Mapped[datetime | None] = mapped_column()
    settled_at: Mapped[datetime | None] = mapped_column()

    user: Mapped["User"] = relationship()
    opportunity: Mapped["Opportunity | None"] = relationship()
    arbitrage: Mapped["ArbitrageOpportunity | None"] = relationship()
    outcome: Mapped["Outcome"] = relationship()
    bookmaker: Mapped["Bookmaker"] = relationship()
    bankroll: Mapped["Bankroll"] = relationship()
