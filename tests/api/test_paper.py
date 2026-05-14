"""Tests API para /api/v1/paper (listing, stats, CLV)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math

import pytest
from sqlalchemy import select

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.models.bookmaker import Bookmaker
from app.models.market import Outcome
from app.models.paper import PaperBet
from app.services.odds_service import OddsIngestionService
from app.services.seed_service import seed_database


class FakeAdapter(DataSourceAdapter):
    def __init__(self, data):
        self.odds_data = data

    async def fetch_odds(self, sport, regions=None, markets=None):
        return self.odds_data

    async def fetch_events(self, sport):
        return []


async def _seed_two_books(db):
    """Crea match con outcomes en bet365 y pinnacle. Retorna (outcomes, bookmakers)."""
    await seed_database(db)
    commence = datetime.now(timezone.utc) + timedelta(days=1)
    data = [
        RawOddsData(
            source="test",
            sport_key="soccer_spain_la_liga",
            league_key="soccer_spain_la_liga",
            home_team="CH",
            away_team="CA",
            commence_time=commence,
            bookmaker=bk,
            market_type="h2h",
            outcomes=[
                RawOutcome(name="CH", price=2.10),
                RawOutcome(name="Draw", price=3.30),
                RawOutcome(name="CA", price=3.60),
            ],
            external_id=f"clv_seed_{bk}",
        )
        for bk in ("bet365", "pinnacle")
    ]
    await OddsIngestionService(FakeAdapter(data)).ingest_odds(
        db, sport_key="football", league_keys=["soccer_spain_la_liga"]
    )
    outcomes = (await db.execute(select(Outcome))).scalars().all()
    books = {b.key: b for b in (await db.execute(select(Bookmaker))).scalars().all()}
    return outcomes, books


def _bet(match_id, outcome, bookmaker, odds_taken, closing_odds, source="value"):
    return PaperBet(
        source_type=source,
        match_id=match_id,
        outcome_id=outcome.id,
        bookmaker_id=bookmaker.id,
        odds_taken=Decimal(odds_taken),
        stake_units=Decimal("0.005"),
        ev_at_placement=Decimal("0.03"),
        closing_odds=Decimal(closing_odds) if closing_odds else None,
    )


class TestPaperCLV:
    async def test_no_paper_bets_returns_empty(self, client):
        response = await client.get("/api/v1/paper/clv")
        assert response.status_code == 200
        data = response.json()
        assert data["total_bets"] == 0
        assert data["bets_with_clv"] == 0
        assert data["coverage_pct"] == 0.0
        assert data["avg_clv_pct"] is None

    async def test_aggregates_clv_correctly(self, client, db_session):
        outcomes, books = await _seed_two_books(db_session)
        from app.models.match import Match
        match = (await db_session.execute(select(Match))).scalar_one()
        ch = next(o for o in outcomes if o.key == "home")

        # 3 bets con CLV, 1 sin closing_odds (cuenta para coverage pero no para promedios)
        # bet365: tomé 2.20 vs cierre 2.00 → CLV +10%
        # bet365: tomé 1.90 vs cierre 2.00 → CLV -5%
        # pinnacle: tomé 2.10 vs cierre 2.00 → CLV +5%
        # bet365 (sin closing): no contribuye
        db_session.add_all([
            _bet(match.id, ch, books["bet365"], "2.20", "2.00"),
            _bet(match.id, ch, books["bet365"], "1.90", "2.00"),
            _bet(match.id, ch, books["pinnacle"], "2.10", "2.00"),
            _bet(match.id, ch, books["bet365"], "2.05", None),
        ])
        await db_session.commit()

        response = await client.get("/api/v1/paper/clv")
        assert response.status_code == 200
        data = response.json()

        assert data["total_bets"] == 4
        assert data["bets_with_clv"] == 3
        assert data["coverage_pct"] == 75.0

        # avg CLV = (0.10 + (-0.05) + 0.05) / 3 = 0.0333...
        assert data["avg_clv_pct"] == pytest.approx((0.10 - 0.05 + 0.05) / 3)
        # median = 0.05 (medio del orden -0.05, 0.05, 0.10)
        assert data["median_clv_pct"] == pytest.approx(0.05)
        # avg log-CLV = mean(ln(2.2/2.0), ln(1.9/2.0), ln(2.1/2.0))
        expected_log = (
            math.log(2.20 / 2.00) + math.log(1.90 / 2.00) + math.log(2.10 / 2.00)
        ) / 3
        assert data["avg_log_clv"] == pytest.approx(expected_log)

        assert data["positive_count"] == 2
        assert data["negative_count"] == 1
        assert data["zero_count"] == 0

        # by_bookmaker: bet365 tiene 2 con CLV, pinnacle 1
        assert data["by_bookmaker"]["bet365"]["bets"] == 2
        assert data["by_bookmaker"]["pinnacle"]["bets"] == 1

    async def test_filters_by_bookmaker(self, client, db_session):
        outcomes, books = await _seed_two_books(db_session)
        from app.models.match import Match
        match = (await db_session.execute(select(Match))).scalar_one()
        ch = next(o for o in outcomes if o.key == "home")

        db_session.add_all([
            _bet(match.id, ch, books["bet365"], "2.20", "2.00"),
            _bet(match.id, ch, books["pinnacle"], "1.95", "2.00"),
        ])
        await db_session.commit()

        response = await client.get("/api/v1/paper/clv?bookmaker_key=bet365")
        assert response.status_code == 200
        data = response.json()
        assert data["bets_with_clv"] == 1
        assert data["avg_clv_pct"] == pytest.approx(0.10)
        assert "pinnacle" not in data["by_bookmaker"]

    async def test_filters_by_source_type(self, client, db_session):
        outcomes, books = await _seed_two_books(db_session)
        from app.models.match import Match
        match = (await db_session.execute(select(Match))).scalar_one()
        ch = next(o for o in outcomes if o.key == "home")

        db_session.add_all([
            _bet(match.id, ch, books["bet365"], "2.20", "2.00", source="value"),
            _bet(match.id, ch, books["pinnacle"], "2.30", "2.00", source="arbitrage"),
        ])
        await db_session.commit()

        response = await client.get("/api/v1/paper/clv?source_type=arbitrage")
        data = response.json()
        assert data["bets_with_clv"] == 1
        assert data["avg_clv_pct"] == pytest.approx(0.15)
