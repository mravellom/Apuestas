from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class Bookmaker(Base):
    __tablename__ = "bookmakers"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    is_sharp: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Comisión sobre ganancia (0.01 = 1%). 0 para books directos típicos.
    commission_pct: Mapped[Decimal] = mapped_column(Numeric(6, 5), default=Decimal("0"))
    # Latencia estimada de ejecución (UI manual vs API vs broker).
    typical_latency_ms: Mapped[int] = mapped_column(default=5000)
    # Si se accede vía broker, FK al broker. NULL = acceso directo.
    broker_id: Mapped[int | None] = mapped_column(ForeignKey("brokers.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    broker: Mapped["Broker | None"] = relationship()
