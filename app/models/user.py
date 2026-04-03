import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(100), unique=True)
    role: Mapped[str] = mapped_column(String(20), default="free")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    config: Mapped["UserConfig | None"] = relationship(back_populates="user", uselist=False)
    bankrolls: Mapped[list["Bankroll"]] = relationship(back_populates="user")
    alerts: Mapped[list["AlertConfig"]] = relationship(back_populates="user")


class UserConfig(Base):
    __tablename__ = "user_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    default_staking: Mapped[str] = mapped_column(String(20), default="fractional_kelly")
    kelly_fraction: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.250"))
    flat_stake_pct: Mapped[Decimal] = mapped_column(Numeric(5, 3), default=Decimal("2.000"))
    min_value_threshold: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.0300"))
    max_stake_pct: Mapped[Decimal] = mapped_column(Numeric(5, 3), default=Decimal("5.000"))
    preferred_sports: Mapped[dict | None] = mapped_column(JSON, default=["football"])
    preferred_leagues: Mapped[dict | None] = mapped_column(JSON, default=[])
    risk_tolerance: Mapped[str] = mapped_column(String(20), default="moderate")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="config")


class Bankroll(Base):
    __tablename__ = "bankrolls"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100), default="Principal")
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    initial_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    current_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="bankrolls")
