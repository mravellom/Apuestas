"""Unit tests para el adapter de The Odds API — foco en parsing de point/parameter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.odds_api import OddsAPIAdapter


def _fake_response(json_data):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_data)
    return resp


def _event_payload(market_key, outcomes):
    return {
        "id": "evt-1",
        "sport_key": "baseball_mlb",
        "commence_time": "2026-04-19T18:00:00Z",
        "home_team": "Home",
        "away_team": "Away",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {"key": market_key, "outcomes": outcomes}
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_totals_parameter_extracted_from_outcome_point():
    """Over 8.5 + Under 8.5 deben producir parameter=8.5 en el RawOddsData."""
    adapter = OddsAPIAdapter(api_key="x", base_url="http://test")
    event = _event_payload(
        "totals",
        [
            {"name": "Over", "price": 1.91, "point": 8.5},
            {"name": "Under", "price": 1.91, "point": 8.5},
        ],
    )

    with patch.object(adapter.client, "get", new=AsyncMock(return_value=_fake_response([event]))):
        data = await adapter.fetch_odds("baseball_mlb")

    assert len(data) == 1
    assert data[0].parameter == 8.5
    assert data[0].outcomes[0].point == 8.5
    assert data[0].outcomes[1].point == 8.5


@pytest.mark.asyncio
async def test_spreads_parameter_uses_abs_value():
    """Home -1.5 + Away +1.5 deben producir parameter=1.5 (valor absoluto)."""
    adapter = OddsAPIAdapter(api_key="x", base_url="http://test")
    event = _event_payload(
        "spreads",
        [
            {"name": "Home", "price": 2.10, "point": -1.5},
            {"name": "Away", "price": 1.80, "point": 1.5},
        ],
    )

    with patch.object(adapter.client, "get", new=AsyncMock(return_value=_fake_response([event]))):
        data = await adapter.fetch_odds("baseball_mlb")

    assert data[0].parameter == 1.5
    # El signo del point per-outcome se preserva para posible uso futuro.
    assert data[0].outcomes[0].point == -1.5
    assert data[0].outcomes[1].point == 1.5


@pytest.mark.asyncio
async def test_spreads_parameter_same_when_outcome_order_reversed():
    """Si un libro invierte el orden de outcomes (Away primero), parameter sigue siendo 1.5."""
    adapter = OddsAPIAdapter(api_key="x", base_url="http://test")
    event = _event_payload(
        "spreads",
        [
            {"name": "Away", "price": 1.75, "point": 1.5},
            {"name": "Home", "price": 2.15, "point": -1.5},
        ],
    )

    with patch.object(adapter.client, "get", new=AsyncMock(return_value=_fake_response([event]))):
        data = await adapter.fetch_odds("baseball_mlb")

    assert data[0].parameter == 1.5


@pytest.mark.asyncio
async def test_h2h_has_no_parameter():
    """h2h sin point: parameter queda None."""
    adapter = OddsAPIAdapter(api_key="x", base_url="http://test")
    event = _event_payload(
        "h2h",
        [
            {"name": "Home", "price": 1.90},
            {"name": "Draw", "price": 3.40},
            {"name": "Away", "price": 4.20},
        ],
    )

    with patch.object(adapter.client, "get", new=AsyncMock(return_value=_fake_response([event]))):
        data = await adapter.fetch_odds("baseball_mlb")

    assert data[0].parameter is None
    assert all(o.point is None for o in data[0].outcomes)


@pytest.mark.asyncio
async def test_different_lines_produce_different_parameters():
    """Mismo match con books en líneas distintas → RawOddsData separados por línea."""
    adapter = OddsAPIAdapter(api_key="x", base_url="http://test")
    # Bypass del allowlist (en el runtime real BOOKMAKERS_ALLOWED filtra bet365).
    adapter.allowed_bookmakers = set()
    event = {
        "id": "evt-1",
        "sport_key": "baseball_mlb",
        "commence_time": "2026-04-19T18:00:00Z",
        "home_team": "Home",
        "away_team": "Away",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.91, "point": 8.5},
                            {"name": "Under", "price": 1.91, "point": 8.5},
                        ],
                    }
                ],
            },
            {
                "key": "bet365",
                "markets": [
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.95, "point": 9.0},
                            {"name": "Under", "price": 1.87, "point": 9.0},
                        ],
                    }
                ],
            },
        ],
    }

    with patch.object(adapter.client, "get", new=AsyncMock(return_value=_fake_response([event]))):
        data = await adapter.fetch_odds("baseball_mlb")

    params = sorted(d.parameter for d in data)
    assert params == [8.5, 9.0]
