"""Unit tests para el adapter de The Odds API — foco en parsing de point/parameter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.odds_api import OddsAPIAdapter


def _fake_response(json_data, status_code: int = 200, headers: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
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
async def test_alternate_totals_normalized_to_totals():
    """`alternate_totals` debe ingerirse como `totals` (mismo market_type base).

    Sin esta normalización, un over 7.5 del endpoint default de un libro no
    matchearía con un over 7.5 del endpoint alt de otro libro — quedarían en
    Markets distintos y el detector nunca formaría arb.
    """
    adapter = OddsAPIAdapter(api_key="x", base_url="http://test")
    event = _event_payload(
        "alternate_totals",
        [
            {"name": "Over", "price": 2.20, "point": 7.5},
            {"name": "Under", "price": 1.70, "point": 7.5},
        ],
    )

    with patch.object(adapter.client, "get", new=AsyncMock(return_value=_fake_response([event]))):
        data = await adapter.fetch_odds("baseball_mlb")

    assert len(data) == 1
    assert data[0].market_type == "totals"
    assert data[0].parameter == 7.5


@pytest.mark.asyncio
async def test_alternate_spreads_normalized_to_spreads():
    """`alternate_spreads` debe ingerirse como `spreads`."""
    adapter = OddsAPIAdapter(api_key="x", base_url="http://test")
    event = _event_payload(
        "alternate_spreads",
        [
            {"name": "Home", "price": 2.50, "point": -2.5},
            {"name": "Away", "price": 1.55, "point": 2.5},
        ],
    )

    with patch.object(adapter.client, "get", new=AsyncMock(return_value=_fake_response([event]))):
        data = await adapter.fetch_odds("basketball_nba")

    assert data[0].market_type == "spreads"
    assert data[0].parameter == 2.5


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


# ── Retry / backoff ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retries_on_5xx_then_succeeds():
    """Un 503 transitorio debe reintentar y entregar el resultado del 2do intento."""
    import httpx
    adapter = OddsAPIAdapter(api_key="x", base_url="http://test", max_retries=2, backoff_base_seconds=0)
    err = _fake_response([], status_code=503)
    err.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("503", request=MagicMock(), response=err))
    ok = _fake_response([])

    with patch.object(adapter.client, "get", new=AsyncMock(side_effect=[err, ok])):
        data = await adapter.fetch_odds("baseball_mlb")
    assert data == []


@pytest.mark.asyncio
async def test_retries_on_429_respects_retry_after():
    """En 429 debe reintentar; mockeamos asyncio.sleep para no esperar de verdad."""
    import httpx
    adapter = OddsAPIAdapter(api_key="x", base_url="http://test", max_retries=2, backoff_base_seconds=0)
    rate_limited = _fake_response([], status_code=429, headers={"retry-after": "5"})
    rate_limited.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("429", request=MagicMock(), response=rate_limited))
    ok = _fake_response([])

    with patch("app.adapters.odds_api.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        with patch.object(adapter.client, "get", new=AsyncMock(side_effect=[rate_limited, ok])):
            data = await adapter.fetch_odds("baseball_mlb")
    assert data == []
    # Debe haber dormido una vez con el retry-after del header (5s)
    sleep_mock.assert_awaited_once_with(5.0)


@pytest.mark.asyncio
async def test_does_not_retry_on_4xx_other_than_429():
    """Un 401 (api key inválida) debe levantar inmediatamente, sin retry."""
    import httpx
    adapter = OddsAPIAdapter(api_key="bad", base_url="http://test", max_retries=3, backoff_base_seconds=0)
    unauth = _fake_response([], status_code=401)
    unauth.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=unauth))

    get_mock = AsyncMock(return_value=unauth)
    with patch.object(adapter.client, "get", new=get_mock):
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.fetch_odds("baseball_mlb")
    # Solo un intento, sin retries
    assert get_mock.await_count == 1


@pytest.mark.asyncio
async def test_retries_on_transport_error_then_succeeds():
    """Un timeout puntual debe reintentar."""
    import httpx
    adapter = OddsAPIAdapter(api_key="x", base_url="http://test", max_retries=2, backoff_base_seconds=0)
    ok = _fake_response([])
    side = [httpx.ConnectTimeout("timeout"), ok]

    with patch.object(adapter.client, "get", new=AsyncMock(side_effect=side)):
        data = await adapter.fetch_odds("baseball_mlb")
    assert data == []


@pytest.mark.asyncio
async def test_gives_up_after_max_retries():
    """Si todos los intentos fallan con 5xx, debe levantar."""
    import httpx
    adapter = OddsAPIAdapter(api_key="x", base_url="http://test", max_retries=2, backoff_base_seconds=0)
    err = _fake_response([], status_code=503)
    err.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("503", request=MagicMock(), response=err))

    get_mock = AsyncMock(return_value=err)
    with patch.object(adapter.client, "get", new=get_mock):
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.fetch_odds("baseball_mlb")
    # 1 inicial + 2 retries = 3 intentos
    assert get_mock.await_count == 3
