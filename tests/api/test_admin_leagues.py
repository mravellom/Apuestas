"""Tests del toggle admin de detection_enabled por liga + seed idempotente."""

from sqlalchemy import select

from app.models.sport import League, Sport
from app.services.seed_service import seed_database


async def _ensure_league(db, sport_key: str, league_key: str, *, enabled: bool):
    sport = (
        await db.execute(select(Sport).where(Sport.key == sport_key))
    ).scalar_one_or_none()
    if sport is None:
        sport = Sport(key=sport_key, name=sport_key)
        db.add(sport)
        await db.flush()
    league = (
        await db.execute(select(League).where(League.key == league_key))
    ).scalar_one_or_none()
    if league is None:
        league = League(
            sport_id=sport.id,
            key=league_key,
            name=league_key,
            detection_enabled=enabled,
        )
        db.add(league)
    else:
        league.detection_enabled = enabled
    await db.commit()
    return league


class TestLeagueToggle:
    async def test_toggle_requires_admin(
        self, client, auth_headers, db_session
    ):
        await _ensure_league(db_session, "football", "test_toggle_unauth", enabled=False)
        r = await client.post(
            "/api/v1/admin/leagues/test_toggle_unauth/toggle",
            headers=auth_headers,
            json={"detection_enabled": True},
        )
        assert r.status_code == 403

    async def test_toggle_unauthenticated(self, client, db_session):
        await _ensure_league(db_session, "football", "test_toggle_noauth", enabled=False)
        r = await client.post(
            "/api/v1/admin/leagues/test_toggle_noauth/toggle",
            json={"detection_enabled": True},
        )
        assert r.status_code == 401

    async def test_toggle_enables_league(
        self, client, admin_headers, db_session
    ):
        await _ensure_league(db_session, "football", "test_toggle_on", enabled=False)
        r = await client.post(
            "/api/v1/admin/leagues/test_toggle_on/toggle",
            headers=admin_headers,
            json={"detection_enabled": True},
        )
        assert r.status_code == 200
        assert r.json()["detection_enabled"] is True

        # Verifica que el cambio persistió en DB
        league = (
            await db_session.execute(
                select(League).where(League.key == "test_toggle_on")
            )
        ).scalar_one()
        await db_session.refresh(league)
        assert league.detection_enabled is True

    async def test_toggle_disables_league(
        self, client, admin_headers, db_session
    ):
        await _ensure_league(db_session, "football", "test_toggle_off", enabled=True)
        r = await client.post(
            "/api/v1/admin/leagues/test_toggle_off/toggle",
            headers=admin_headers,
            json={"detection_enabled": False},
        )
        assert r.status_code == 200
        assert r.json()["detection_enabled"] is False

    async def test_toggle_unknown_league_404(
        self, client, admin_headers
    ):
        r = await client.post(
            "/api/v1/admin/leagues/nonexistent_league/toggle",
            headers=admin_headers,
            json={"detection_enabled": True},
        )
        assert r.status_code == 404

    async def test_list_leagues_admin(
        self, client, admin_headers, db_session
    ):
        await _ensure_league(db_session, "football", "test_list_a", enabled=True)
        await _ensure_league(db_session, "football", "test_list_b", enabled=False)
        r = await client.get("/api/v1/admin/leagues", headers=admin_headers)
        assert r.status_code == 200
        keys = {lg["key"] for lg in r.json()}
        assert "test_list_a" in keys
        assert "test_list_b" in keys


class TestSeedIdempotency:
    async def test_seed_does_not_override_manual_toggle(self, db_session):
        """Si el usuario toggleó una liga, el seed no debe sobrescribir su decisión."""
        # Primera corrida del seed — crea WNBA con detection_enabled=False.
        await seed_database(db_session)
        wnba = (
            await db_session.execute(
                select(League).where(League.key == "basketball_wnba")
            )
        ).scalar_one()
        assert wnba.detection_enabled is False

        # Usuario la activa via toggle.
        wnba.detection_enabled = True
        await db_session.commit()

        # Segunda corrida del seed — NO debe revertir a False.
        await seed_database(db_session)
        await db_session.refresh(wnba)
        assert wnba.detection_enabled is True

    async def test_seed_creates_womens_leagues_as_disabled(self, db_session):
        await seed_database(db_session)
        for key in ("basketball_wnba", "soccer_usa_nwsl", "soccer_england_efl_womens"):
            lg = (
                await db_session.execute(select(League).where(League.key == key))
            ).scalar_one_or_none()
            assert lg is not None, f"Liga {key} no seedeada"
            assert lg.detection_enabled is False, f"Liga {key} debe estar disabled por default"
