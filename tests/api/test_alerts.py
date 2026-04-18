"""Tests API para /api/v1/alerts/config (CRUD de alertas premium)."""

from decimal import Decimal

from sqlalchemy import select

from app.models.alert import AlertConfig


class TestListAlerts:
    async def test_free_user_forbidden(self, client, auth_headers):
        response = await client.get("/api/v1/alerts/config", headers=auth_headers)
        assert response.status_code == 403

    async def test_premium_empty(self, client, premium_headers):
        response = await client.get("/api/v1/alerts/config", headers=premium_headers)
        assert response.status_code == 200
        assert response.json() == []

    async def test_premium_sees_only_their_alerts(
        self, client, premium_headers, premium_user, test_user, db_session
    ):
        # Alert for premium_user
        db_session.add(
            AlertConfig(
                user_id=premium_user.id,
                channel="telegram",
                destination="premium-chat",
                min_value_pct=Decimal("0.05"),
                active=True,
            )
        )
        # Alert for another user (should NOT appear)
        db_session.add(
            AlertConfig(
                user_id=test_user.id,
                channel="telegram",
                destination="other-chat",
                min_value_pct=Decimal("0.05"),
                active=True,
            )
        )
        await db_session.commit()

        response = await client.get("/api/v1/alerts/config", headers=premium_headers)
        data = response.json()
        assert len(data) == 1
        assert data[0]["destination"] == "premium-chat"


class TestCreateAlert:
    async def test_create_with_defaults(self, client, premium_headers):
        response = await client.post(
            "/api/v1/alerts/config",
            headers=premium_headers,
            json={"channel": "telegram", "destination": "chat-1"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["channel"] == "telegram"
        assert data["destination"] == "chat-1"
        assert data["min_value_pct"] == 0.05  # default
        assert data["active"] is True

    async def test_create_with_filters(self, client, premium_headers):
        response = await client.post(
            "/api/v1/alerts/config",
            headers=premium_headers,
            json={
                "channel": "webhook",
                "destination": "https://hook.example/notify",
                "min_value_pct": 0.10,
                "sports_filter": ["football"],
                "leagues_filter": ["soccer_epl"],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["min_value_pct"] == 0.10
        assert data["sports_filter"] == ["football"]
        assert data["leagues_filter"] == ["soccer_epl"]

    async def test_invalid_channel_rejected(self, client, premium_headers):
        response = await client.post(
            "/api/v1/alerts/config",
            headers=premium_headers,
            json={"channel": "carrier_pigeon", "destination": "x"},
        )
        assert response.status_code == 422

    async def test_min_value_out_of_range_rejected(self, client, premium_headers):
        response = await client.post(
            "/api/v1/alerts/config",
            headers=premium_headers,
            json={"channel": "telegram", "destination": "x", "min_value_pct": 2.0},
        )
        assert response.status_code == 422

    async def test_enforces_max_10_alerts(
        self, client, premium_headers, premium_user, db_session
    ):
        for i in range(10):
            db_session.add(
                AlertConfig(
                    user_id=premium_user.id,
                    channel="telegram",
                    destination=f"chat-{i}",
                    min_value_pct=Decimal("0.05"),
                    active=True,
                )
            )
        await db_session.commit()

        response = await client.post(
            "/api/v1/alerts/config",
            headers=premium_headers,
            json={"channel": "telegram", "destination": "chat-11"},
        )
        assert response.status_code == 400
        assert "Maximum 10" in response.json()["detail"]

    async def test_free_user_cannot_create(self, client, auth_headers):
        response = await client.post(
            "/api/v1/alerts/config",
            headers=auth_headers,
            json={"channel": "telegram", "destination": "x"},
        )
        assert response.status_code == 403


class TestUpdateAlert:
    async def test_update_own_alert(
        self, client, premium_headers, premium_user, db_session
    ):
        alert = AlertConfig(
            user_id=premium_user.id,
            channel="telegram",
            destination="old",
            min_value_pct=Decimal("0.05"),
            active=True,
        )
        db_session.add(alert)
        await db_session.commit()
        await db_session.refresh(alert)

        response = await client.put(
            f"/api/v1/alerts/config/{alert.id}",
            headers=premium_headers,
            json={"destination": "new", "min_value_pct": 0.20, "active": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["destination"] == "new"
        assert data["min_value_pct"] == 0.20
        assert data["active"] is False

    async def test_update_rejects_other_users_alert(
        self, client, premium_headers, test_user, db_session
    ):
        alert = AlertConfig(
            user_id=test_user.id,
            channel="telegram",
            destination="foreign",
            min_value_pct=Decimal("0.05"),
            active=True,
        )
        db_session.add(alert)
        await db_session.commit()
        await db_session.refresh(alert)

        response = await client.put(
            f"/api/v1/alerts/config/{alert.id}",
            headers=premium_headers,
            json={"destination": "hacked"},
        )
        assert response.status_code == 404

    async def test_update_missing_returns_404(self, client, premium_headers):
        response = await client.put(
            "/api/v1/alerts/config/9999",
            headers=premium_headers,
            json={"destination": "x"},
        )
        assert response.status_code == 404


class TestDeleteAlert:
    async def test_delete_own_alert(
        self, client, premium_headers, premium_user, db_session
    ):
        alert = AlertConfig(
            user_id=premium_user.id,
            channel="telegram",
            destination="to-delete",
            min_value_pct=Decimal("0.05"),
            active=True,
        )
        db_session.add(alert)
        await db_session.commit()
        await db_session.refresh(alert)
        alert_id = alert.id

        response = await client.delete(
            f"/api/v1/alerts/config/{alert_id}", headers=premium_headers
        )
        assert response.status_code == 204

        # Alert gone from DB
        remaining = (
            await db_session.execute(
                select(AlertConfig).where(AlertConfig.id == alert_id)
            )
        ).scalar_one_or_none()
        assert remaining is None

    async def test_delete_rejects_other_users_alert(
        self, client, premium_headers, test_user, db_session
    ):
        alert = AlertConfig(
            user_id=test_user.id,
            channel="telegram",
            destination="foreign",
            min_value_pct=Decimal("0.05"),
            active=True,
        )
        db_session.add(alert)
        await db_session.commit()
        await db_session.refresh(alert)

        response = await client.delete(
            f"/api/v1/alerts/config/{alert.id}", headers=premium_headers
        )
        assert response.status_code == 404

    async def test_delete_missing_returns_404(self, client, premium_headers):
        response = await client.delete(
            "/api/v1/alerts/config/9999", headers=premium_headers
        )
        assert response.status_code == 404
