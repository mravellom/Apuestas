import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class AlertConfig(Base):
    __tablename__ = "alerts_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    channel: Mapped[str] = mapped_column(String(20))
    destination: Mapped[str] = mapped_column(String(500))
    min_value_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.0500"))
    sports_filter: Mapped[dict | None] = mapped_column(JSON, default=[])
    leagues_filter: Mapped[dict | None] = mapped_column(JSON, default=[])
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="alerts")
