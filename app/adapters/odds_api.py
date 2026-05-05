"""Adapter para The Odds API v4."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.config import settings

logger = logging.getLogger(__name__)


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


def _parse_retry_after(headers) -> float | None:
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class OddsAPIAdapter(DataSourceAdapter):
    SOURCE = "odds_api"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        max_retries: int = 3,
        backoff_base_seconds: float = 1.0,
    ):
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
        # Retries + backoff exponencial. Por defecto 3 intentos extra (4 total)
        # con base 1s → 1, 2, 4 segundos. En 429 se respeta Retry-After si llega.
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds

    def _capture_usage(self, response: httpx.Response, endpoint: str, sport: str | None):
        self.last_usage = ApiUsageSnapshot(
            endpoint=endpoint,
            sport_key=sport,
            requests_remaining=_parse_int_header(response.headers, "x-requests-remaining"),
            requests_used=_parse_int_header(response.headers, "x-requests-used"),
        )

    async def _get_with_retry(
        self, url: str, params: dict, endpoint: str, sport: str | None
    ) -> httpx.Response:
        """GET con retry exponencial.

        Reintenta en: errores de transporte (red, DNS, timeout), 5xx, 429.
        Respeta `Retry-After` en 429. NO reintenta en 4xx (excepto 429) — esos
        son errores del cliente (api key inválida, sport mal escrito) que no se
        arreglan repitiendo.
        """
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.get(url, params=params)
                if response.status_code == 429:
                    if attempt == self.max_retries:
                        response.raise_for_status()
                    delay = _parse_retry_after(response.headers) or (
                        self.backoff_base_seconds * (2 ** attempt)
                    )
                    logger.warning(
                        "Odds API 429 on %s/%s; sleeping %.1fs (attempt %d/%d)",
                        endpoint, sport, delay, attempt + 1, self.max_retries + 1,
                    )
                    await asyncio.sleep(delay)
                    continue
                if response.status_code >= 500:
                    if attempt == self.max_retries:
                        response.raise_for_status()
                    delay = self.backoff_base_seconds * (2 ** attempt)
                    logger.warning(
                        "Odds API %d on %s/%s; sleeping %.1fs (attempt %d/%d)",
                        response.status_code, endpoint, sport, delay,
                        attempt + 1, self.max_retries + 1,
                    )
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                return response
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_exc = e
                if attempt == self.max_retries:
                    raise
                delay = self.backoff_base_seconds * (2 ** attempt)
                logger.warning(
                    "Odds API transport error on %s/%s (%s); sleeping %.1fs (attempt %d/%d)",
                    endpoint, sport, type(e).__name__, delay,
                    attempt + 1, self.max_retries + 1,
                )
                await asyncio.sleep(delay)
        # Unreachable: o devolvemos response, o raise dentro del loop.
        if last_exc:
            raise last_exc
        raise RuntimeError("retry loop exited without returning")

    async def fetch_events(self, sport: str) -> list[dict]:
        """Obtiene lista de eventos para un deporte."""
        url = f"{self.base_url}/sports/{sport}/events"
        response = await self._get_with_retry(
            url, {"apiKey": self.api_key}, "events", sport
        )
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

        response = await self._get_with_retry(url, params, "odds", sport)
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
