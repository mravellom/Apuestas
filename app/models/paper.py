"""Paper trading: apuestas simuladas para validar el edge sin arriesgar dinero."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class PaperBet(Base):
    __tablename__ = "paper_bets"
    __table_args__ = (
        Index("idx_paper_result", "result"),
        Index("idx_paper_match", "match_id"),
        Index("idx_paper_opp", "opportunity_id"),
        Index("idx_paper_arb", "arbitrage_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 'value' (single leg) or 'arbitrage' (one row per leg)
    source_type: Mapped[str] = mapped_column(String(20))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id", ondelete="SET NULL"))
    arbitrage_id: Mapped[int | None] = mapped_column(ForeignKey("arbitrage_opportunities.id", ondelete="SET NULL"))
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    outcome_id: Mapped[int] = mapped_column(ForeignKey("outcomes.id", ondelete="CASCADE"))
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id"))
    odds_taken: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    # Comisión efectiva del libro/broker en el momento del placement (0..1).
    # Snapshot: si el broker o el book cambia su comisión, el paper bet histórico
    # mantiene la comisión real al momento del registro. Se aplica al settle de
    # `won`: profit = stake * (odds - 1) * (1 - commission).
    commission_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    # Stake como fracción de bankroll (ej. 0.0020 = 0.2% Kelly/4). Unidades abstractas.
    stake_units: Mapped[Decimal] = mapped_column(Numeric(8, 5))
    ev_at_placement: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    # Cuota de cierre del mismo (outcome, bookmaker) — capturada por
    # capture_closing_lines_job ~5min antes del kickoff. CLV = odds_taken/closing_odds - 1.
    closing_odds: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    placed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # 'pending' | 'won' | 'lost' | 'void'
    result: Mapped[str] = mapped_column(String(20), default="pending")
    resolved_at: Mapped[datetime | None] = mapped_column()
    # Signed: +stake*(odds-1) si won, -stake si lost, 0 si void
    profit_units: Mapped[Decimal | None] = mapped_column(Numeric(10, 5))

    match: Mapped["Match"] = relationship()
    outcome: Mapped["Outcome"] = relationship()
    bookmaker: Mapped["Bookmaker"] = relationship()
    opportunity: Mapped["Opportunity | None"] = relationship()
    arbitrage: Mapped["ArbitrageOpportunity | None"] = relationship()
