"""Tests API para /api/v1/matches (list, detail, odds)."""

from datetime import datetime, timedelta, timezone

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.services.odds_service import OddsIngestionService
from app.services.seed_service import seed_database


class FakeAdapter(DataSourceAdapter):
    def __init__(self, odds_data):
        self.odds_data = odds_data

    async def fetch_odds(self, sport, regions=None, markets=None):
        return self.odds_data

    async def fetch_events(self, sport):
        return []


def _raw(home, away, bk, outcomes, commence, league="soccer_spain_la_liga"):
    return RawOddsData(
        source="test",
        sport_key=league,
        league_key=league,
        home_team=home,
        away_team=away,
        commence_time=commence,
        bookmaker=bk,
        market_type="h2h",
        outcomes=[RawOutcome(name=n, price=p) for n, p in outcomes],
        external_id=f"match_api_{home}_{away}_{bk}",
    )


async def _seed_match(
    db,
    home: str = "Home",
    away: str = "Away",
    commence: datetime | None = None,
    league: str = "soccer_spain_la_liga",
):
    if commence is None:
        commence = datetime.now(timezone.utc) + timedelta(days=1)
    await seed_database(db)
    data = [
        _raw(home, away, "bet365",
             [(home, 2.10), ("Draw", 3.30), (away, 3.60)], commence, league),
        _raw(home, away, "pinnacle",
             [(home, 2.12), ("Draw", 3.25), (away, 3.55)], commence, league),
    ]
    await OddsIngestionService(FakeAdapter(data)).ingest_odds(
        db, sport_key="football", league_keys=[league]
    )


class TestListMatches:
    async def test_requires_auth(self, client):
        response = await client.get("/api/v1/matches")
        assert response.status_code == 401

    async def test_empty_list(self, client, auth_headers):
        response = await client.get("/api/v1/matches", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_returns_match(self, client, auth_headers, db_session):
        await _seed_match(db_session, home="Valencia", away="Getafe")

        response = await client.get("/api/v1/matches", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        m = data[0]
        assert m["home_team"]["canonical_name"] == "Valencia"
        assert m["away_team"]["canonical_name"] == "Getafe"
        assert m["status"] == "scheduled"

    async def test_filter_by_sport(self, client, auth_headers, db_session):
        await _seed_match(db_session, home="H1", away="A1")

        ok = await client.get(
            "/api/v1/matches?sport=football", headers=auth_headers
        )
        assert len(ok.json()) == 1

        none = await client.get(
            "/api/v1/matches?sport=basketball", headers=auth_headers
        )
        assert none.json() == []

    async def test_filter_by_league(self, client, auth_headers, db_session):
        await _seed_match(
            db_session, home="L1", away="L2", league="soccer_spain_la_liga"
        )

        ok = await client.get(
            "/api/v1/matches?sport=football&league=soccer_spain_la_liga",
            headers=auth_headers,
        )
        assert len(ok.json()) == 1

        none = await client.get(
            "/api/v1/matches?sport=football&league=soccer_epl",
            headers=auth_headers,
        )
        assert none.json() == []

    async def test_filter_by_status(self, client, auth_headers, db_session):
        await _seed_match(db_session)

        scheduled = await client.get(
            "/api/v1/matches?status=scheduled", headers=auth_headers
        )
        assert len(scheduled.json()) == 1

        completed = await client.get(
            "/api/v1/matches?status=completed", headers=auth_headers
        )
        assert completed.json() == []

    async def test_filter_by_date_range(self, client, auth_headers, db_session):
        from urllib.parse import quote

        commence = datetime.now(timezone.utc) + timedelta(days=3)
        await _seed_match(db_session, commence=commence)

        # Match in 3 days — filter for tomorrow → miss
        tomorrow = quote((datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        response = await client.get(
            f"/api/v1/matches?date_to={tomorrow}", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json() == []

        # Wider window → hit
        in_a_week = quote((datetime.now(timezone.utc) + timedelta(days=7)).isoformat())
        response = await client.get(
            f"/api/v1/matches?date_to={in_a_week}", headers=auth_headers
        )
        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_pagination(self, client, auth_headers, db_session):
        base = datetime.now(timezone.utc) + timedelta(days=1)
        for i in range(3):
            await _seed_match(
                db_session,
                home=f"HP{i}",
                away=f"AP{i}",
                commence=base + timedelta(hours=i),
            )

        page1 = await client.get(
            "/api/v1/matches?page=1&page_size=2", headers=auth_headers
        )
        page2 = await client.get(
            "/api/v1/matches?page=2&page_size=2", headers=auth_headers
        )
        assert len(page1.json()) == 2
        assert len(page2.json()) == 1
        ids_1 = {m["id"] for m in page1.json()}
        ids_2 = {m["id"] for m in page2.json()}
        assert ids_1.isdisjoint(ids_2)


class TestGetMatch:
    async def test_missing_returns_404(self, client, auth_headers):
        response = await client.get("/api/v1/matches/9999", headers=auth_headers)
        assert response.status_code == 404

    async def test_detail_includes_markets_and_outcomes(
        self, client, auth_headers, db_session
    ):
        await _seed_match(db_session, home="Detail H", away="Detail A")

        list_resp = await client.get("/api/v1/matches", headers=auth_headers)
        match_id = list_resp.json()[0]["id"]

        response = await client.get(
            f"/api/v1/matches/{match_id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == match_id
        assert data["home_team"]["canonical_name"] == "Detail H"
        assert len(data["markets"]) == 1
        market = data["markets"][0]
        assert market["market_type_key"] == "h2h"
        assert len(market["outcomes"]) == 3
        outcome_keys = {o["key"] for o in market["outcomes"]}
        # h2h/spreads outcome keys se canonizan a home/away (via TeamNormalizer.
        # resolve_side); "draw" es literal. Esto evita que dos libros con
        # variantes del nombre del mismo equipo creen Outcome rows distintos.
        assert outcome_keys == {"home", "draw", "away"}


class TestMatchOdds:
    async def test_missing_match_returns_404(self, client, auth_headers):
        response = await client.get(
            "/api/v1/matches/9999/odds", headers=auth_headers
        )
        assert response.status_code == 404

    async def test_returns_latest_odds_per_bookmaker(
        self, client, auth_headers, db_session
    ):
        await _seed_match(db_session, home="OH", away="OA")

        list_resp = await client.get("/api/v1/matches", headers=auth_headers)
        match_id = list_resp.json()[0]["id"]

        response = await client.get(
            f"/api/v1/matches/{match_id}/odds", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        # 3 outcomes × 2 bookmakers = 6
        assert len(data) == 6

        row = data[0]
        expected = {
            "outcome_id", "outcome_key", "outcome_name",
            "bookmaker_key", "bookmaker_name",
            "price", "captured_at",
        }
        assert expected <= set(row.keys())
        bookmakers = {row["bookmaker_key"] for row in data}
        assert bookmakers == {"bet365", "pinnacle"}
