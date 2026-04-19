"""Interfaz base para adaptadores de fuentes de datos."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawOutcome:
    name: str
    price: float
    # Handicap o total line asociado al outcome (e.g. +1.5, -1.5, 8.5). None
    # para mercados planos como h2h. The Odds API lo publica a este nivel,
    # no a nivel market.
    point: float | None = None


@dataclass
class RawOddsData:
    """Datos crudos de una fuente, antes de normalizar."""

    source: str
    sport_key: str
    league_key: str | None
    home_team: str
    away_team: str
    commence_time: datetime
    bookmaker: str
    market_type: str
    outcomes: list[RawOutcome] = field(default_factory=list)
    parameter: float | None = None
    external_id: str | None = None


class DataSourceAdapter(ABC):
    @abstractmethod
    async def fetch_odds(
        self, sport: str, regions: list[str] | None = None, markets: list[str] | None = None
    ) -> list[RawOddsData]:
        """Obtiene cuotas de la fuente externa."""
        ...

    @abstractmethod
    async def fetch_events(self, sport: str) -> list[dict]:
        """Obtiene lista de eventos/partidos."""
        ...
