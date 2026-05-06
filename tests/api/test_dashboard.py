"""Tests API para GET /api/v1/dashboard/summary."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.api_usage import ApiUsageLog
from app.services.seed_service import seed_database

# Reuse the seed helper from arbitrage tests so we have a real arb in DB.
from tests.api.test_arbitrage import _seed_arbitrage


@pytest.mark.asyncio
class TestDashboardSummary:
    async def test_basic_shape(self, client, auth_headers, db_session):
        await seed_database(db_session)

        resp = await client.get(
            "/api/v1/dashboard/summary?window_days=7", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()

        # Core sections present
        assert {
            "window_days",
            "generated_at",
            "sports",
            "top_leagues_by_arbs",
            "top_books_arbs",
            "top_books_valuebets",
            "api_usage",
        } <= set(body.keys())
        assert body["window_days"] == 7
        assert isinstance(body["sports"], list)
        # seed_database creates a handful of sports
        assert len(body["sports"]) > 0

    async def test_sport_counts_reflect_arbs(self, client, auth_headers, db_session):
        await _seed_arbitrage(db_session)
        await db_session.commit()

        resp = await client.get(
            "/api/v1/dashboard/summary?window_days=30", headers=auth_headers
        )
        body = resp.json()

        football = next((s for s in body["sports"] if s["sport_key"] == "football"), None)
        assert football is not None
        assert football["arbs"] >= 1

        # And it shows up in top leagues
        assert any(
            l["league_key"] == "soccer_spain_la_liga"
            for l in body["top_leagues_by_arbs"]
        )

    async def test_book_counts_reflect_arb_legs(self, client, auth_headers, db_session):
        await _seed_arbitrage(db_session)
        await db_session.commit()

        resp = await client.get(
            "/api/v1/dashboard/summary?window_days=30", headers=auth_headers
        )
        body = resp.json()

        # The arb seed uses 5 books; some of them should appear among top books
        book_keys = {b["bookmaker"] for b in body["top_books_arbs"]}
        assert book_keys & {"bet365", "pinnacle", "betfair_ex_eu", "williamhill", "unibet_eu"}

    async def test_window_days_validation(self, client, auth_headers):
        bad_low = await client.get(
            "/api/v1/dashboard/summary?window_days=0", headers=auth_headers
        )
        assert bad_low.status_code == 422
        bad_high = await client.get(
            "/api/v1/dashboard/summary?window_days=999", headers=auth_headers
        )
        assert bad_high.status_code == 422

    async def test_hourly_distribution_in_chilean_time(
        self, client, auth_headers, db_session
    ):
        """24 buckets de horas en CLT con conteos reales convertidos desde UTC."""
        await _seed_arbitrage(db_session)
        # Forzar el detected_at del arb a 03:00 UTC = 23:00 CLT (UTC-4) o
        # 00:00 CLT (UTC-3 con DST). Usamos enero (CLST UTC-3) para predecibilidad.
        from app.models.arbitrage import ArbitrageOpportunity
        from sqlalchemy import select

        arb = (await db_session.execute(select(ArbitrageOpportunity))).scalar_one()
        arb.detected_at = datetime(2026, 1, 15, 3, 0, 0)  # 00:00 CLST (UTC-3)
        await db_session.commit()

        resp = await client.get(
            "/api/v1/dashboard/summary?window_days=365", headers=auth_headers
        )
        body = resp.json()

        # 24 buckets, todos representados (relleno con 0)
        assert len(body["arbs_by_hour_clt"]) == 24
        assert {b["hour"] for b in body["arbs_by_hour_clt"]} == set(range(24))
        # El arb a 03:00 UTC (enero) = 00:00 CLT
        bucket_0 = next(b for b in body["arbs_by_hour_clt"] if b["hour"] == 0)
        assert bucket_0["count"] == 1
        # Total debe coincidir con cantidad de arbs
        assert sum(b["count"] for b in body["arbs_by_hour_clt"]) == 1

        # Value bets: misma estructura, en este escenario sin opportunities → 0
        assert len(body["valuebets_by_hour_clt"]) == 24
        assert sum(b["count"] for b in body["valuebets_by_hour_clt"]) == 0

    async def test_api_usage_reflects_persisted_logs(
        self, client, auth_headers, db_session
    ):
        await seed_database(db_session)
        # Insert a fake usage log
        db_session.add(
            ApiUsageLog(
                source="odds_api",
                sport_key="football",
                endpoint="odds",
                requests_remaining=4500,
                requests_used=500,
                captured_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/api/v1/dashboard/summary", headers=auth_headers
        )
        body = resp.json()
        odds_api = next((u for u in body["api_usage"] if u["source"] == "odds_api"), None)
        assert odds_api is not None
        assert odds_api["requests_remaining"] == 4500
        assert odds_api["requests_used"] == 500
        assert odds_api["calls_24h"] >= 1
