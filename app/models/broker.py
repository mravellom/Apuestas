"""Brokers de apuestas (SportMarket, AsianConnect, etc.).

Un broker es un intermediario que da acceso a múltiples books con una sola
cuenta. Los books accedidos vía broker tienen comisión y latencia distintas
a los directos.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class Broker(Base):
    __tablename__ = "brokers"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    # Comisión por defecto sobre ganancia (0.01 = 1%).
    # Puede sobreescribirse por bookmaker individual.
    default_commission_pct: Mapped[Decimal] = mapped_column(Numeric(6, 5), default=Decimal("0"))
    # Latencia típica de ejecución en ms.
    typical_latency_ms: Mapped[int] = mapped_column(default=1000)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
