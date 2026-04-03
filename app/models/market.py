from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class MarketType(Base):
    __tablename__ = "market_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)


class Market(Base):
    __tablename__ = "markets"
    __table_args__ = (UniqueConstraint("match_id", "market_type_id", "parameter"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    market_type_id: Mapped[int] = mapped_column(ForeignKey("market_types.id"))
    parameter: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    match: Mapped["Match"] = relationship(back_populates="markets")
    market_type: Mapped["MarketType"] = relationship()
    outcomes: Mapped[list["Outcome"]] = relationship(back_populates="market")


class Outcome(Base):
    __tablename__ = "outcomes"
    __table_args__ = (UniqueConstraint("market_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))

    market: Mapped["Market"] = relationship(back_populates="outcomes")
    odds: Mapped[list["Odds"]] = relationship(back_populates="outcome")


class Odds(Base):
    __tablename__ = "odds"
    __table_args__ = (
        Index("idx_odds_outcome_bookmaker", "outcome_id", "bookmaker_id"),
        Index("idx_odds_captured", "captured_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    outcome_id: Mapped[int] = mapped_column(ForeignKey("outcomes.id", ondelete="CASCADE"))
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id"))
    price: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    captured_at: Mapped[datetime] = mapped_column(server_default=func.now())
    source: Mapped[str] = mapped_column(String(50))

    outcome: Mapped["Outcome"] = relationship(back_populates="odds")
    bookmaker: Mapped["Bookmaker"] = relationship()
