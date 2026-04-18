"""Tests API para /api/v1/opportunities (listar, detalle, take)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.models.opportunity import BetTracking, Opportunity
from app.models.user import Bankroll
from app.services.odds_service import OddsIngestionService
from app.services.opportunity_service import OpportunityDetectionService
from app.services.seed_service import seed_database


class FakeAdapter(DataSourceAdapter):
    def __init__(self, odds_data):
        self.odds_data = odds_data

    async def fetch_odds(self, sport, regions=None, markets=None):
        return self.odds_data

    async def fetch_events(self, sport):
        return []


def _raw(home, away, bk, outcomes, commence):
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
        external_id=f"opps_api_{home}_{away}_{bk}",
    )


async def _seed_value_bet(
    db: AsyncSession,
    home: str = "Team A",
    away: str = "Team B",
) -> list[Opportunity]:
    """Seeds an outlier scenario and runs the detector. Returns created opps."""
    await seed_database(db)
    commence = datetime.now(timezone.utc) + timedelta(days=1)
    data = [
        _raw(home, away, "bet365", [(home, 2.10), ("Draw", 3.30), (away, 3.60)], commence),
        _raw(home, away, "pinnacle", [(home, 2.12), ("Draw", 3.25), (away, 3.55)], commence),
        _raw(home, away, "betfair_ex_eu", [(home, 2.08), ("Draw", 3.35), (away, 3.65)], commence),
        _raw(home, away, "williamhill", [(home, 2.60), ("Draw", 2.90), (away, 2.80)], commence),
    ]
    await OddsIngestionService(FakeAdapter(data)).ingest_odds(
        db, sport_key="football", league_keys=["soccer_spain_la_liga"]
    )
    detector = OpportunityDetectionService(min_value=0.01, min_bookmakers=3)
    _, new_opps = await detector.detect_all(db)
    return new_opps


class TestListOpportunities:
    async def test_requires_auth(self, client):
        response = await client.get("/api/v1/opportunities")
        assert response.status_code == 401

    async def test_empty_list(self, client, auth_headers):
        response = await client.get("/api/v1/opportunities", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    async def test_returns_active_opportunities(
        self, client, auth_headers, db_session
    ):
        opps = await _seed_value_bet(db_session)
        assert opps, "precondition: detector must create opportunities"

        response = await client.get("/api/v1/opportunities", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

        row = data[0]
        expected = {
            "id", "match_home_team", "match_away_team", "commence_time",
            "market_type", "outcome_name", "bookmaker_name",
            "odds_price", "consensus_prob", "implied_prob", "value_pct",
            "kelly_stake_pct", "status", "detected_at",
        }
        assert expected <= set(row.keys())
        assert row["status"] == "active"
        assert row["odds_price"] > 1.0

    async def test_ordered_by_value_desc(
        self, client, auth_headers, db_session
    ):
        await _seed_value_bet(db_session, home="T1", away="T2")
        response = await client.get("/api/v1/opportunities", headers=auth_headers)
        data = response.json()
        if len(data) > 1:
            values = [row["value_pct"] for row in data]
            assert values == sorted(values, reverse=True)

    async def test_min_value_filter(self, client, auth_headers, db_session):
        opps = await _seed_value_bet(db_session)
        max_value = max(float(o.value_pct) for o in opps)

        # Above max → empty
        high = await client.get(
            f"/api/v1/opportunities?min_value={max_value + 1}",
            headers=auth_headers,
        )
        assert high.status_code == 200
        assert high.json() == []

        # Below any → results
        low = await client.get(
            "/api/v1/opportunities?min_value=0", headers=auth_headers
        )
        assert len(low.json()) >= 1

    async def test_free_user_capped_at_5(
        self, client, auth_headers, db_session
    ):
        """Free-tier response is capped at 5 rows regardless of page_size."""
        # Force many opportunities by seeding 7 distinct matches
        for i in range(7):
            await _seed_value_bet(db_session, home=f"H{i}", away=f"A{i}")

        total = (await db_session.execute(select(Opportunity))).scalars().all()
        assert len(total) > 5

        response = await client.get(
            "/api/v1/opportunities?page_size=50", headers=auth_headers
        )
        assert response.status_code == 200
        assert len(response.json()) == 5

    async def test_premium_pagination(
        self, client, premium_headers, db_session
    ):
        for i in range(3):
            await _seed_value_bet(db_session, home=f"PH{i}", away=f"PA{i}")

        total_rows = (await db_session.execute(select(Opportunity))).scalars().all()
        total_count = len(total_rows)
        assert total_count >= 3

        page1 = await client.get(
            "/api/v1/opportunities?page=1&page_size=2", headers=premium_headers
        )
        page2 = await client.get(
            "/api/v1/opportunities?page=2&page_size=2", headers=premium_headers
        )
        assert page1.status_code == 200 and page2.status_code == 200
        assert len(page1.json()) == 2
        # page2 should have at least one more row (or be empty if exactly 2 total)
        assert len(page2.json()) <= 2
        # No overlap between pages
        ids_1 = {row["id"] for row in page1.json()}
        ids_2 = {row["id"] for row in page2.json()}
        assert ids_1.isdisjoint(ids_2)


class TestOpportunityDetail:
    async def test_detail_returns_404_when_missing(self, client, auth_headers):
        response = await client.get(
            "/api/v1/opportunities/9999", headers=auth_headers
        )
        assert response.status_code == 404

    async def test_detail_returns_opportunity(
        self, client, auth_headers, db_session
    ):
        opps = await _seed_value_bet(db_session)
        opp_id = opps[0].id

        response = await client.get(
            f"/api/v1/opportunities/{opp_id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == opp_id
        # Detail-only fields
        assert "recommended_stake" in data
        assert "staking_method" in data
        assert "bankroll_used" in data

    async def test_detail_with_bankroll_recommends_stake(
        self, client, auth_headers, db_session, test_user
    ):
        opps = await _seed_value_bet(db_session)
        # Give the user a bankroll so the detail can compute a recommendation
        db_session.add(
            Bankroll(
                user_id=test_user.id,
                name="Main",
                currency="EUR",
                initial_amount=Decimal("1000"),
                current_amount=Decimal("1000"),
            )
        )
        await db_session.commit()

        response = await client.get(
            f"/api/v1/opportunities/{opps[0].id}", headers=auth_headers
        )
        data = response.json()
        assert data["recommended_stake"] is not None
        assert data["recommended_stake"] > 0
        assert data["bankroll_used"] == 1000.0
        assert data["staking_method"] is not None


class TestTakeOpportunity:
    async def test_take_creates_bet_and_deducts_bankroll(
        self, client, auth_headers, db_session, test_user
    ):
        opps = await _seed_value_bet(db_session)
        opp_id = opps[0].id

        bankroll = Bankroll(
            user_id=test_user.id,
            name="Main",
            currency="EUR",
            initial_amount=Decimal("1000"),
            current_amount=Decimal("1000"),
        )
        db_session.add(bankroll)
        await db_session.commit()
        await db_session.refresh(bankroll)

        response = await client.post(
            f"/api/v1/opportunities/{opp_id}/take",
            headers=auth_headers,
            json={"bankroll_id": bankroll.id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["stake_amount"] > 0
        assert data["odds_at_placement"] > 1.0
        assert data["staking_method"] in {"fractional_kelly", "flat", "kelly"}

        # Bet persisted
        bets = (await db_session.execute(select(BetTracking))).scalars().all()
        assert len(bets) == 1
        assert bets[0].user_id == test_user.id

        # Bankroll debited
        await db_session.refresh(bankroll)
        assert bankroll.current_amount < Decimal("1000")

    async def test_take_rejects_other_users_bankroll(
        self, client, auth_headers, premium_user, db_session
    ):
        opps = await _seed_value_bet(db_session)
        # Bankroll owned by a different user
        bankroll = Bankroll(
            user_id=premium_user.id,
            name="Other",
            currency="EUR",
            initial_amount=Decimal("500"),
            current_amount=Decimal("500"),
        )
        db_session.add(bankroll)
        await db_session.commit()
        await db_session.refresh(bankroll)

        response = await client.post(
            f"/api/v1/opportunities/{opps[0].id}/take",
            headers=auth_headers,
            json={"bankroll_id": bankroll.id},
        )
        assert response.status_code == 404

    async def test_take_rejects_nonactive_opportunity(
        self, client, auth_headers, db_session, test_user
    ):
        opps = await _seed_value_bet(db_session)
        opp = opps[0]
        opp.status = "expired"
        bankroll = Bankroll(
            user_id=test_user.id,
            name="Main",
            currency="EUR",
            initial_amount=Decimal("100"),
            current_amount=Decimal("100"),
        )
        db_session.add(bankroll)
        await db_session.commit()
        await db_session.refresh(bankroll)

        response = await client.post(
            f"/api/v1/opportunities/{opp.id}/take",
            headers=auth_headers,
            json={"bankroll_id": bankroll.id},
        )
        assert response.status_code == 404
