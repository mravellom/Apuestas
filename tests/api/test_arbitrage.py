"""Tests API para GET /api/v1/arbitrage."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.models.arbitrage import ArbitrageOpportunity
from app.services.arbitrage_service import ArbitrageDetectionService
from app.services.odds_service import OddsIngestionService
from app.services.seed_service import seed_database


class FakeAdapter(DataSourceAdapter):
    def __init__(self, odds_data: list[RawOddsData]):
        self.odds_data = odds_data

    async def fetch_odds(self, sport, regions=None, markets=None):
        return self.odds_data

    async def fetch_events(self, sport):
        return []


def _raw(home: str, away: str, bk: str, outcomes: list[tuple[str, float]],
         commence: datetime) -> RawOddsData:
    return RawOddsData(
        source="test",
        sport_key="soccer_spain_la_liga",
        league_key="soccer_spain_la_liga",
        home_team=home,
        away_team=away,
        commence_time=commence,
        bookmaker=bk,
        market_type="h2h",
        outcomes=[RawOutcome(name=n, price=p) for n, p in outcomes],
        external_id=f"arb_api_{home}_{away}_{bk}",
    )


async def _seed_arbitrage(
    db: AsyncSession,
    home: str = "ArbHome",
    away: str = "ArbAway",
    commence: datetime | None = None,
) -> None:
    """Best cross-bookmaker odds form a ~12.9% arb."""
    if commence is None:
        commence = datetime.now(timezone.utc) + timedelta(days=1)
    await seed_database(db)
    data = [
        _raw(home, away, "bet365", [(home, 2.60), ("Draw", 3.10), (away, 3.20)], commence),
        _raw(home, away, "pinnacle", [(home, 2.00), ("Draw", 3.80), (away, 3.20)], commence),
        _raw(home, away, "betfair_ex_eu", [(home, 2.00), ("Draw", 3.10), (away, 4.20)], commence),
        _raw(home, away, "williamhill", [(home, 2.30), ("Draw", 3.40), (away, 3.60)], commence),
        _raw(home, away, "unibet_eu", [(home, 2.10), ("Draw", 3.50), (away, 3.50)], commence),
    ]
    await OddsIngestionService(FakeAdapter(data)).ingest_odds(
        db, sport_key="football", league_keys=["soccer_spain_la_liga"]
    )
    await ArbitrageDetectionService(min_bookmakers=5).detect_all(db)


class TestListArbitrage:
    async def test_empty_list(self, client, auth_headers):
        response = await client.get("/api/v1/arbitrage/", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    async def test_returns_active_arbs(self, client, auth_headers, db_session):
        await _seed_arbitrage(db_session)

        response = await client.get("/api/v1/arbitrage/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

        arb = data[0]
        assert arb["status"] == "active"
        assert arb["profit_pct"] > 0.5
        assert arb["total_implied"] < 1.0
        assert arb["market_type"] == "h2h"
        assert "ArbHome" in arb["match"] and "ArbAway" in arb["match"]
        assert " vs " in arb["match"]
        assert len(arb["legs"]) == 3
        # Required keys per leg
        for leg in arb["legs"]:
            assert {"outcome", "outcome_name", "bookmaker", "odds", "stake_pct"} <= leg.keys()

    async def test_ordered_by_profit_desc(
        self, client, auth_headers, db_session
    ):
        """Several arbs must come back sorted by profit_pct descending."""
        await _seed_arbitrage(db_session, home="H1", away="A1")
        await _seed_arbitrage(db_session, home="H2", away="A2",
                              commence=datetime.now(timezone.utc) + timedelta(days=2))

        response = await client.get("/api/v1/arbitrage/", headers=auth_headers)
        data = response.json()
        assert len(data) >= 2
        profits = [row["profit_pct"] for row in data]
        assert profits == sorted(profits, reverse=True)


class TestFilters:
    async def test_min_profit_filter(self, client, auth_headers, db_session):
        await _seed_arbitrage(db_session)

        # Very high threshold → nothing
        high = await client.get(
            "/api/v1/arbitrage/?min_profit=100", headers=auth_headers
        )
        assert high.status_code == 200
        assert high.json() == []

        # Low threshold → sees it
        low = await client.get(
            "/api/v1/arbitrage/?min_profit=0.1", headers=auth_headers
        )
        assert low.status_code == 200
        assert len(low.json()) >= 1

    async def test_status_filter_returns_expired(
        self, client, auth_headers, db_session
    ):
        await _seed_arbitrage(db_session)

        # Manually flip the arb to expired
        arb = (await db_session.execute(select(ArbitrageOpportunity))).scalar_one()
        arb.status = "expired"
        arb.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db_session.commit()

        active = await client.get(
            "/api/v1/arbitrage/?status=active", headers=auth_headers
        )
        assert active.json() == []

        expired = await client.get(
            "/api/v1/arbitrage/?status=expired", headers=auth_headers
        )
        assert len(expired.json()) == 1
        assert expired.json()[0]["status"] == "expired"


class TestResponseShape:
    async def test_response_has_expected_fields(
        self, client, auth_headers, db_session
    ):
        await _seed_arbitrage(db_session)
        response = await client.get("/api/v1/arbitrage/", headers=auth_headers)
        arb = response.json()[0]
        expected = {
            "id", "match", "commence_time", "market_type",
            "profit_pct", "total_implied", "legs", "status", "detected_at",
        }
        assert expected <= set(arb.keys())

    async def test_profit_pct_is_float_not_decimal(
        self, client, auth_headers, db_session
    ):
        await _seed_arbitrage(db_session)
        arb = (await client.get("/api/v1/arbitrage/", headers=auth_headers)).json()[0]
        # JSON must deserialize to native float, not string (DecimalField trap)
        assert isinstance(arb["profit_pct"], (int, float))
        assert not isinstance(arb["profit_pct"], Decimal)


class TestHistoryDateFilter:
    async def test_from_date_excludes_older_arbs(
        self, client, auth_headers, db_session
    ):
        await _seed_arbitrage(db_session)

        # Push the arb's detected_at into the past
        arb = (await db_session.execute(select(ArbitrageOpportunity))).scalar_one()
        arb.detected_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        await db_session.commit()

        today = datetime.now(timezone.utc).date().isoformat()
        old = (datetime.now(timezone.utc).date() - timedelta(days=15)).isoformat()

        # from_date today excludes the 10-day-old arb
        filtered = await client.get(
            f"/api/v1/arbitrage/history?from_date={today}", headers=auth_headers
        )
        assert filtered.status_code == 200
        assert filtered.json() == []

        # from_date 15 days ago includes it
        included = await client.get(
            f"/api/v1/arbitrage/history?from_date={old}", headers=auth_headers
        )
        assert len(included.json()) == 1

    async def test_to_date_is_inclusive_end_of_day(
        self, client, auth_headers, db_session
    ):
        await _seed_arbitrage(db_session)

        arb = (await db_session.execute(select(ArbitrageOpportunity))).scalar_one()
        target_day = datetime(2026, 4, 1, 23, 30, 0)
        arb.detected_at = target_day
        await db_session.commit()

        # to_date = same day → must include (end-of-day inclusive)
        same_day = await client.get(
            "/api/v1/arbitrage/history?to_date=2026-04-01", headers=auth_headers
        )
        assert len(same_day.json()) == 1

        # to_date = day before → must exclude
        day_before = await client.get(
            "/api/v1/arbitrage/history?to_date=2026-03-31", headers=auth_headers
        )
        assert day_before.json() == []

    async def test_invalid_date_returns_422(
        self, client, auth_headers
    ):
        bad = await client.get(
            "/api/v1/arbitrage/history?from_date=not-a-date", headers=auth_headers
        )
        assert bad.status_code == 422
