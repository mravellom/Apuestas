
from app.models.sport import League, Sport


class TestSports:
    async def test_list_sports_empty(self, client, auth_headers):
        response = await client.get("/api/v1/sports", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_sports_with_data(self, client, auth_headers, db_session):
        sport = Sport(key="football", name="Football", active=True)
        db_session.add(sport)
        await db_session.commit()

        response = await client.get("/api/v1/sports", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["key"] == "football"

    async def test_list_sports_unauthenticated(self, client):
        response = await client.get("/api/v1/sports")
        assert response.status_code == 401

    async def test_list_leagues(self, client, auth_headers, db_session):
        sport = Sport(key="football2", name="Football", active=True)
        db_session.add(sport)
        await db_session.flush()

        league = League(sport_id=sport.id, key="spain_la_liga", name="La Liga", country="Spain")
        db_session.add(league)
        await db_session.commit()

        response = await client.get("/api/v1/sports/football2/leagues", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["key"] == "spain_la_liga"


class TestAlerts:
    async def test_alerts_require_premium(self, client, auth_headers):
        response = await client.get("/api/v1/alerts/config", headers=auth_headers)
        assert response.status_code == 403

    async def test_alerts_premium_can_access(self, client, premium_headers):
        response = await client.get("/api/v1/alerts/config", headers=premium_headers)
        assert response.status_code == 200

    async def test_create_alert(self, client, premium_headers):
        response = await client.post("/api/v1/alerts/config", headers=premium_headers, json={
            "channel": "telegram",
            "destination": "123456789",
            "min_value_pct": 0.05,
        })
        assert response.status_code == 201
        data = response.json()
        assert data["channel"] == "telegram"
        assert data["active"] is True
