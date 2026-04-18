"""
Scraper para obtener cuotas desde fuentes web públicas.

Implementa DataSourceAdapter usando datos JSON de APIs públicas de comparación
de cuotas. Este scraper sirve como complemento a The Odds API para obtener
cuotas de bookmakers no cubiertos por la API principal.

NOTA: Este scraper está diseñado para funcionar con APIs JSON públicas.
Para sitios que requieren renderizado JavaScript, se necesitaría Playwright.
"""

import logging
from datetime import datetime

from app.adapters.base import RawOddsData, RawOutcome
from app.adapters.scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# Mapping de ligas a URLs de APIs públicas de cuotas
LEAGUE_ENDPOINTS: dict[str, str] = {
    # Estas URLs son ejemplos — deben configurarse para cada fuente real
    # "soccer_spain_la_liga": "https://example.com/api/odds/la-liga",
}


class OddsScraperAdapter(BaseScraper):
    """
    Scraper complementario para cuotas deportivas.

    Funciona parseando APIs JSON públicas de sitios de comparación de cuotas.
    Diseñado como complemento a The Odds API para cubrir bookmakers adicionales.

    Uso:
        adapter = OddsScraperAdapter()
        odds = await adapter.fetch_odds("soccer_spain_la_liga")
    """

    SOURCE = "scraper_web"

    def __init__(
        self,
        endpoints: dict[str, str] | None = None,
        max_retries: int = 3,
    ):
        super().__init__(max_retries=max_retries)
        self.endpoints = endpoints or LEAGUE_ENDPOINTS

    async def fetch_events(self, sport: str) -> list[dict]:
        """Obtiene lista de eventos disponibles."""
        # Default: return empty — each sport/league needs specific endpoint config
        return []

    async def fetch_odds(
        self,
        sport: str,
        regions: list[str] | None = None,
        markets: list[str] | None = None,
    ) -> list[RawOddsData]:
        """
        Obtiene cuotas scrapeando fuentes web.

        Args:
            sport: key de la liga (ej: "soccer_spain_la_liga")
            regions: no usado (el scraper define sus propias fuentes)
            markets: tipos de mercado a extraer (default: ["h2h"])
        """
        markets = markets or ["h2h"]
        endpoint = self.endpoints.get(sport)
        if not endpoint:
            logger.debug("No endpoint configured for %s", sport)
            return []

        data = await self._fetch_json(endpoint)
        if not data:
            return []

        return self._parse_response(data, sport, markets)

    def _parse_response(
        self, data: dict, sport_key: str, markets: list[str]
    ) -> list[RawOddsData]:
        """
        Parsea la respuesta JSON al formato estándar RawOddsData.

        El formato esperado es:
        {
            "events": [
                {
                    "home": "Team A",
                    "away": "Team B",
                    "commence": "2025-01-15T20:00:00Z",
                    "bookmakers": {
                        "bookmaker_key": {
                            "h2h": {"home": 2.10, "draw": 3.30, "away": 3.60}
                        }
                    }
                }
            ]
        }

        Adapta este parser según la estructura real de tu fuente de datos.
        """
        raw_data: list[RawOddsData] = []
        events = data.get("events", [])

        for event in events:
            home = event.get("home", "")
            away = event.get("away", "")
            commence_str = event.get("commence", "")

            if not home or not away or not commence_str:
                continue

            try:
                commence_time = datetime.fromisoformat(
                    commence_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except ValueError:
                continue

            bookmakers = event.get("bookmakers", {})
            for bk_key, bk_markets in bookmakers.items():
                for market_type in markets:
                    market_data = bk_markets.get(market_type, {})
                    if not market_data:
                        continue

                    outcomes = self._extract_outcomes(market_data, market_type, home, away)
                    if not outcomes:
                        continue

                    raw_data.append(
                        RawOddsData(
                            source=self.SOURCE,
                            sport_key=sport_key,
                            league_key=sport_key,
                            home_team=home,
                            away_team=away,
                            commence_time=commence_time,
                            bookmaker=bk_key,
                            market_type=market_type,
                            outcomes=outcomes,
                            parameter=market_data.get("parameter"),
                            external_id=event.get("id"),
                        )
                    )

        return raw_data

    def _extract_outcomes(
        self, market_data: dict, market_type: str, home: str, away: str
    ) -> list[RawOutcome]:
        """Extrae outcomes de los datos de un mercado."""
        outcomes: list[RawOutcome] = []

        if market_type == "h2h":
            home_odds = market_data.get("home") or market_data.get("1")
            draw_odds = market_data.get("draw") or market_data.get("X")
            away_odds = market_data.get("away") or market_data.get("2")

            if home_odds and away_odds:
                outcomes.append(RawOutcome(name=home, price=float(home_odds)))
                if draw_odds:
                    outcomes.append(RawOutcome(name="Draw", price=float(draw_odds)))
                outcomes.append(RawOutcome(name=away, price=float(away_odds)))

        elif market_type == "totals":
            over_odds = market_data.get("over")
            under_odds = market_data.get("under")
            if over_odds and under_odds:
                outcomes.append(RawOutcome(name="Over", price=float(over_odds)))
                outcomes.append(RawOutcome(name="Under", price=float(under_odds)))

        return outcomes
