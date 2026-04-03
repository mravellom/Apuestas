"""Base para scrapers web."""

import logging

import httpx

from app.adapters.base import DataSourceAdapter

logger = logging.getLogger(__name__)


class BaseScraper(DataSourceAdapter):
    """Base class para scrapers con manejo de headers, retries y rate limiting."""

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    def __init__(self, max_retries: int = 3, timeout: float = 15.0):
        self.max_retries = max_retries
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers=self.DEFAULT_HEADERS,
            follow_redirects=True,
        )

    async def _fetch_page(self, url: str) -> str | None:
        """Obtiene el HTML de una página con reintentos."""
        for attempt in range(self.max_retries):
            try:
                response = await self.client.get(url)
                if response.status_code == 200:
                    return response.text
                logger.warning(
                    "HTTP %d fetching %s (attempt %d/%d)",
                    response.status_code, url, attempt + 1, self.max_retries,
                )
            except Exception as e:
                logger.warning(
                    "Error fetching %s (attempt %d/%d): %s",
                    url, attempt + 1, self.max_retries, e,
                )
        return None

    async def _fetch_json(self, url: str, headers: dict | None = None) -> dict | None:
        """Obtiene JSON de un endpoint con reintentos."""
        for attempt in range(self.max_retries):
            try:
                response = await self.client.get(url, headers=headers or {})
                if response.status_code == 200:
                    return response.json()
                logger.warning(
                    "HTTP %d fetching %s (attempt %d/%d)",
                    response.status_code, url, attempt + 1, self.max_retries,
                )
            except Exception as e:
                logger.warning(
                    "Error fetching %s (attempt %d/%d): %s",
                    url, attempt + 1, self.max_retries, e,
                )
        return None

    async def close(self):
        await self.client.aclose()
