"""Modelo de oportunidades de arbitraje (surebets)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class ArbitrageOpportunity(Base):
    __tablename__ = "arbitrage_opportunities"
    __table_args__ = (
        Index("idx_arb_status", "status"),
        Index("idx_arb_profit", "profit_pct"),
        Index("idx_arb_match_market", "match_id", "market_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id", ondelete="CASCADE"))
    total_implied: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    profit_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    num_outcomes: Mapped[int] = mapped_column()
    legs: Mapped[dict] = mapped_column(JSON)  # [{outcome, bookmaker, odds, stake_pct}, ...]
    status: Mapped[str] = mapped_column(String(20), default="active")
    detected_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column()
    closed_at: Mapped[datetime | None] = mapped_column()
    # Snapshot del último sweep_dead_arbs sobre este arb. Permite al frontend
    # distinguir "alive sin revalidar en N min" vs "alive recién revalidado"
    # sin pegarle al endpoint /revalidate por cada fila.
    last_revalidate_at: Mapped[datetime | None] = mapped_column()
    last_revalidate_status: Mapped[str | None] = mapped_column(String(20))
    last_revalidate_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))

    match: Mapped["Match"] = relationship()
    market: Mapped["Market"] = relationship()
