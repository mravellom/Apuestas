"""Adapter para The Odds API v4."""

from dataclasses import dataclass
from datetime import datetime

import httpx

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.config import settings


@dataclass
class ApiUsageSnapshot:
    """Headers de cuota devueltos por The Odds API en cada request."""
    endpoint: str
    sport_key: str | None
    requests_remaining: int | None
    requests_used: int | None


def _parse_int_header(headers, key: str) -> int | None:
    raw = headers.get(key)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


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
        # Última lectura de headers de cuota; el caller la persiste.
        self.last_usage: ApiUsageSnapshot | None = None

    def _capture_usage(self, response: httpx.Response, endpoint: str, sport: str | None):
        self.last_usage = ApiUsageSnapshot(
            endpoint=endpoint,
            sport_key=sport,
            requests_remaining=_parse_int_header(response.headers, "x-requests-remaining"),
            requests_used=_parse_int_header(response.headers, "x-requests-used"),
        )

    async def fetch_events(self, sport: str) -> list[dict]:
        """Obtiene lista de eventos para un deporte."""
        url = f"{self.base_url}/sports/{sport}/events"
        response = await self.client.get(url, params={"apiKey": self.api_key})
        response.raise_for_status()
        self._capture_usage(response, "events", sport)
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
        self._capture_usage(response, "odds", sport)

        raw_data: list[RawOddsData] = []
        for event in response.json():
            commence_time = datetime.fromisoformat(
                event["commence_time"].replace("Z", "+00:00")
            ).replace(tzinfo=None)

            for bookmaker in event.get("bookmakers", []):
                if self.allowed_bookmakers and bookmaker["key"].lower() not in self.allowed_bookmakers:
                    continue
                for market in bookmaker.get("markets", []):
                    outcomes_raw = market.get("outcomes", [])
                    outcomes = [
                        RawOutcome(
                            name=o["name"],
                            price=o["price"],
                            point=float(o["point"]) if o.get("point") is not None else None,
                        )
                        for o in outcomes_raw
                    ]
                    # The Odds API pone `point` a nivel outcome, no market:
                    #   totals  → ambos outcomes con el mismo punto (over/under 8.5)
                    #   spreads → puntos simétricos (-1.5 home / +1.5 away)
                    #   h2h     → sin point
                    # Para agrupar libros que cotizan la misma línea usamos el
                    # valor absoluto del primer point no-nulo. Así bet365 con
                    # home=-1.5/away=+1.5 y pinnacle con away=+1.5/home=-1.5
                    # caen al mismo market "spreads 1.5".
                    line = next(
                        (abs(o.point) for o in outcomes if o.point is not None),
                        None,
                    )
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
                            parameter=line,
                            external_id=event.get("id"),
                        )
                    )

        return raw_data

    async def close(self):
        await self.client.aclose()
