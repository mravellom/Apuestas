"""Adapter para The Odds API v4."""

from datetime import datetime

import httpx

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.config import settings


class OddsAPIAdapter(DataSourceAdapter):
    SOURCE = "odds_api"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.ODDS_API_KEY
        self.base_url = base_url or settings.ODDS_API_BASE_URL
        self.client = httpx.AsyncClient(timeout=30.0)
        self.allowed_bookmakers = {
            b.strip().lower()
            for b in settings.BOOKMAKERS_ALLOWED.split(",")
            if b.strip()
        }

    async def fetch_events(self, sport: str) -> list[dict]:
        """Obtiene lista de eventos para un deporte."""
        url = f"{self.base_url}/sports/{sport}/events"
        response = await self.client.get(url, params={"apiKey": self.api_key})
        response.raise_for_status()
        return response.json()

    async def fetch_odds(
        self,
        sport: str,
        regions: list[str] | None = None,
        markets: list[str] | None = None,
    ) -> list[RawOddsData]:
        """
        Obtiene cuotas desde The Odds API.

        Args:
            sport: clave del deporte (ej: "soccer_spain_la_liga")
            regions: regiones de bookmakers (ej: ["eu", "uk"])
            markets: tipos de mercado (ej: ["h2h", "totals"])
        """
        regions = regions or ["eu", "uk"]
        markets = markets or ["h2h"]

        url = f"{self.base_url}/sports/{sport}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": ",".join(regions),
            "markets": ",".join(markets),
            "oddsFormat": "decimal",
        }

        response = await self.client.get(url, params=params)
        response.raise_for_status()

        raw_data: list[RawOddsData] = []
        for event in response.json():
            commence_time = datetime.fromisoformat(
                event["commence_time"].replace("Z", "+00:00")
            ).replace(tzinfo=None)

            for bookmaker in event.get("bookmakers", []):
                if self.allowed_bookmakers and bookmaker["key"].lower() not in self.allowed_bookmakers:
                    continue
                for market in bookmaker.get("markets", []):
                    outcomes = [
                        RawOutcome(name=o["name"], price=o["price"])
                        for o in market.get("outcomes", [])
                    ]
                    point = market.get("point")
                    raw_data.append(
                        RawOddsData(
                            source=self.SOURCE,
                            sport_key=event.get("sport_key", sport),
                            league_key=event.get("sport_key", sport),
                            home_team=event["home_team"],
                            away_team=event["away_team"],
                            commence_time=commence_time,
                            bookmaker=bookmaker["key"],
                            market_type=market["key"],
                            outcomes=outcomes,
                            parameter=float(point) if point is not None else None,
                            external_id=event.get("id"),
                        )
                    )

        return raw_data

    async def close(self):
        await self.client.aclose()
