"""Tests para el scraper complementario."""

from unittest.mock import patch

from app.adapters.scraper.oddschecker import OddsScraperAdapter


class TestOddsScraperAdapter:
    def setup_method(self):
        self.adapter = OddsScraperAdapter(
            endpoints={"soccer_spain_la_liga": "https://example.com/api/la-liga"}
        )

    async def test_fetch_odds_no_endpoint(self):
        adapter = OddsScraperAdapter(endpoints={})
        result = await adapter.fetch_odds("soccer_unknown_league")
        assert result == []

    async def test_fetch_odds_parses_json(self):
        mock_data = {
            "events": [
                {
                    "home": "Real Madrid",
                    "away": "Barcelona",
                    "commence": "2025-12-15T20:00:00Z",
                    "id": "evt_001",
                    "bookmakers": {
                        "codere": {
                            "h2h": {"home": 2.30, "draw": 3.10, "away": 3.20}
                        },
                        "kirolbet": {
                            "h2h": {"home": 2.25, "draw": 3.15, "away": 3.30}
                        },
                    },
                }
            ]
        }

        with patch.object(self.adapter, "_fetch_json", return_value=mock_data):
            result = await self.adapter.fetch_odds("soccer_spain_la_liga")

        assert len(result) == 2  # 2 bookmakers
        assert result[0].source == "scraper_web"
        assert result[0].home_team == "Real Madrid"
        assert result[0].away_team == "Barcelona"
        assert result[0].bookmaker in ("codere", "kirolbet")
        assert len(result[0].outcomes) == 3  # home, draw, away

    async def test_fetch_odds_handles_empty_response(self):
        with patch.object(self.adapter, "_fetch_json", return_value=None):
            result = await self.adapter.fetch_odds("soccer_spain_la_liga")
        assert result == []

    async def test_fetch_odds_handles_missing_fields(self):
        mock_data = {
            "events": [
                {"home": "", "away": "Barcelona", "commence": "2025-12-15T20:00:00Z"},
                {"home": "Real Madrid", "away": "", "commence": "2025-12-15T20:00:00Z"},
                {"home": "Real Madrid", "away": "Barcelona", "commence": ""},
            ]
        }

        with patch.object(self.adapter, "_fetch_json", return_value=mock_data):
            result = await self.adapter.fetch_odds("soccer_spain_la_liga")
        assert result == []

    async def test_parse_totals_market(self):
        mock_data = {
            "events": [
                {
                    "home": "Valencia",
                    "away": "Sevilla",
                    "commence": "2025-12-15T18:00:00Z",
                    "bookmakers": {
                        "codere": {
                            "totals": {"over": 1.85, "under": 2.05, "parameter": 2.5}
                        }
                    },
                }
            ]
        }

        with patch.object(self.adapter, "_fetch_json", return_value=mock_data):
            result = await self.adapter.fetch_odds("soccer_spain_la_liga", markets=["totals"])

        assert len(result) == 1
        assert len(result[0].outcomes) == 2
        assert result[0].outcomes[0].name == "Over"
        assert result[0].outcomes[1].name == "Under"

    async def test_fetch_events_returns_empty(self):
        result = await self.adapter.fetch_events("football")
        assert result == []
