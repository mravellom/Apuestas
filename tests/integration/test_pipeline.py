"""Tests end-to-end del pipeline: seed → ingest → detect → verify."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.models.bookmaker import Bookmaker
from app.models.market import Odds, Outcome
from app.models.match import Match
from app.models.opportunity import Opportunity
from app.models.sport import Sport
from app.models.team import Team
from app.services.odds_service import OddsIngestionService
from app.services.opportunity_service import OpportunityDetectionService
from app.services.seed_service import seed_database


def make_raw_odds(
    home: str = "Real Madrid",
    away: str = "Barcelona",
    bookmaker: str = "bet365",
    outcomes: list[tuple[str, float]] | None = None,
    commence_time: datetime | None = None,
) -> RawOddsData:
    """Helper para crear RawOddsData de test."""
    if outcomes is None:
        outcomes = [("Real Madrid", 2.10), ("Draw", 3.30), ("Barcelona", 3.60)]
    if commence_time is None:
        commence_time = datetime.now(timezone.utc) + timedelta(days=1)

    return RawOddsData(
        source="test",
        sport_key="soccer_spain_la_liga",
        league_key="soccer_spain_la_liga",
        home_team=home,
        away_team=away,
        commence_time=commence_time,
        bookmaker=bookmaker,
        market_type="h2h",
        outcomes=[RawOutcome(name=n, price=p) for n, p in outcomes],
        external_id=f"test_{home}_{away}",
    )


class FakeAdapter(DataSourceAdapter):
    """Adapter falso que retorna datos predefinidos."""

    def __init__(self, odds_data: list[RawOddsData] | None = None):
        self.odds_data = odds_data or []

    async def fetch_odds(self, sport, regions=None, markets=None):
        return self.odds_data

    async def fetch_events(self, sport):
        return []


class TestSeedDatabase:
    async def test_seed_creates_data(self, db_session: AsyncSession):
        counts = await seed_database(db_session)
        assert counts["sports"] > 0
        assert counts["leagues"] > 0
        assert counts["market_types"] > 0
        assert counts["bookmakers"] > 0

        # Verify data exists
        sports = await db_session.execute(select(Sport))
        assert len(sports.scalars().all()) >= 1

        bookmakers = await db_session.execute(select(Bookmaker))
        bks = bookmakers.scalars().all()
        assert len(bks) >= 10
        # Verify sharp bookmakers
        sharps = [b for b in bks if b.is_sharp]
        assert len(sharps) >= 2

    async def test_seed_is_idempotent(self, db_session: AsyncSession):
        await seed_database(db_session)
        counts2 = await seed_database(db_session)
        # Second run should insert nothing
        assert all(v == 0 for v in counts2.values())


class TestOddsIngestion:
    async def test_ingest_creates_match_and_odds(self, db_session: AsyncSession):
        await seed_database(db_session)

        commence = datetime.now(timezone.utc) + timedelta(days=1)
        fake_data = [
            make_raw_odds("Real Madrid", "Barcelona", "bet365",
                          [("Real Madrid", 2.10), ("Draw", 3.30), ("Barcelona", 3.60)],
                          commence),
            make_raw_odds("Real Madrid", "Barcelona", "pinnacle",
                          [("Real Madrid", 2.12), ("Draw", 3.25), ("Barcelona", 3.55)],
                          commence),
            make_raw_odds("Real Madrid", "Barcelona", "betfair_ex_eu",
                          [("Real Madrid", 2.05), ("Draw", 3.40), ("Barcelona", 3.50)],
                          commence),
        ]

        adapter = FakeAdapter(fake_data)
        service = OddsIngestionService(adapter)
        counts = await service.ingest_odds(
            db_session,
            sport_key="football",
            league_keys=["soccer_spain_la_liga"],
        )

        assert counts["events"] == 1
        assert counts["odds_saved"] == 3  # 3 bookmakers
        assert counts["errors"] == 0

        # Verify match was created
        matches = await db_session.execute(select(Match))
        match_list = matches.scalars().all()
        assert len(match_list) == 1

        # Verify teams were created
        teams = await db_session.execute(select(Team))
        team_list = teams.scalars().all()
        assert len(team_list) == 2

        # Verify outcomes
        outcomes = await db_session.execute(select(Outcome))
        outcome_list = outcomes.scalars().all()
        assert len(outcome_list) == 3  # home, draw, away

        # Verify odds saved (3 bookmakers × 3 outcomes = 9)
        odds = await db_session.execute(select(Odds))
        odds_list = odds.scalars().all()
        assert len(odds_list) == 9

    async def test_ingest_idempotent_match(self, db_session: AsyncSession):
        """Ingesting twice shouldn't duplicate matches."""
        await seed_database(db_session)

        commence = datetime.now(timezone.utc) + timedelta(days=1)
        fake_data = [
            make_raw_odds("Atletico", "Sevilla", "bet365",
                          [("Atletico", 1.80), ("Draw", 3.50), ("Sevilla", 4.20)],
                          commence),
        ]

        adapter = FakeAdapter(fake_data)
        service = OddsIngestionService(adapter)

        await service.ingest_odds(db_session, sport_key="football",
                                  league_keys=["soccer_spain_la_liga"])
        await service.ingest_odds(db_session, sport_key="football",
                                  league_keys=["soccer_spain_la_liga"])

        matches = await db_session.execute(select(Match))
        assert len(matches.scalars().all()) == 1

        # But odds should be duplicated (historical tracking)
        odds = await db_session.execute(select(Odds))
        assert len(odds.scalars().all()) == 6  # 3 outcomes × 2 ingestions


class TestOpportunityDetection:
    async def _setup_match_with_odds(self, db: AsyncSession) -> Match:
        """Helper: seed + ingest odds with a value bet scenario."""
        await seed_database(db)

        commence = datetime.now(timezone.utc) + timedelta(days=1)

        # Create odds where one bookmaker offers significantly higher odds
        # than the consensus → this creates a value bet
        fake_data = [
            make_raw_odds("Valencia", "Villarreal", "bet365",
                          [("Valencia", 2.10), ("Draw", 3.30), ("Villarreal", 3.60)],
                          commence),
            make_raw_odds("Valencia", "Villarreal", "pinnacle",
                          [("Valencia", 2.12), ("Draw", 3.25), ("Villarreal", 3.55)],
                          commence),
            make_raw_odds("Valencia", "Villarreal", "betfair_ex_eu",
                          [("Valencia", 2.08), ("Draw", 3.35), ("Villarreal", 3.65)],
                          commence),
            # William Hill offers much higher home odds → potential value
            make_raw_odds("Valencia", "Villarreal", "williamhill",
                          [("Valencia", 2.50), ("Draw", 3.10), ("Villarreal", 3.00)],
                          commence),
        ]

        adapter = FakeAdapter(fake_data)
        service = OddsIngestionService(adapter)
        await service.ingest_odds(db, sport_key="football",
                                  league_keys=["soccer_spain_la_liga"])

        result = await db.execute(select(Match))
        return result.scalar_one()

    async def test_detect_finds_value_bets(self, db_session: AsyncSession):
        await self._setup_match_with_odds(db_session)

        detector = OpportunityDetectionService(min_value=0.01, min_bookmakers=3)
        counts, new_opps = await detector.detect_all(db_session)

        assert counts["opportunities_found"] > 0
        assert counts["errors"] == 0

        # Verify opportunities in DB
        opps = await db_session.execute(
            select(Opportunity).where(Opportunity.status == "active")
        )
        opportunities = opps.scalars().all()
        assert len(opportunities) > 0

        for opp in opportunities:
            assert float(opp.value_pct) >= 0.01
            assert float(opp.consensus_prob) > 0
            assert float(opp.odds_price) > 1

    async def test_detect_excludes_stale_odds_from_consensus(
        self, db_session: AsyncSession
    ):
        """Odds older than max_odds_age_minutes must not contribute to consensus."""
        match = await self._setup_match_with_odds(db_session)

        # Push williamhill's odds (the soft-outlier 2.50 home) into the past so
        # they're stale. Without the cutoff, that 2.50 would inflate the
        # implied prob in the consensus and emit a fantom value bet at a price
        # nobody currently offers.
        wh = (
            await db_session.execute(
                select(Bookmaker).where(Bookmaker.key == "williamhill")
            )
        ).scalar_one()
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=5)
        await db_session.execute(
            Odds.__table__.update()
            .where(Odds.bookmaker_id == wh.id)
            .values(captured_at=old)
        )
        await db_session.flush()

        detector = OpportunityDetectionService(
            min_value=0.01, min_bookmakers=3, max_odds_age_minutes=30
        )
        _, opps = await detector.detect_all(db_session)
        # No value bet should reference williamhill since its odds are stale
        wh_bets = [o for o in opps if o.bookmaker_id == wh.id]
        assert wh_bets == []

    async def test_detect_widening_age_window_lets_stale_odds_back_in(
        self, db_session: AsyncSession
    ):
        """Loose max_odds_age_minutes restores the previous (buggy) behavior — sanity for the knob."""
        await self._setup_match_with_odds(db_session)
        wh = (
            await db_session.execute(
                select(Bookmaker).where(Bookmaker.key == "williamhill")
            )
        ).scalar_one()
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=5)
        await db_session.execute(
            Odds.__table__.update()
            .where(Odds.bookmaker_id == wh.id)
            .values(captured_at=old)
        )
        await db_session.flush()

        # 7-day window includes the 5h-old odds → williamhill back in the pool
        detector = OpportunityDetectionService(
            min_value=0.01, min_bookmakers=3, max_odds_age_minutes=10080
        )
        _, opps = await detector.detect_all(db_session)
        # With WH back in consensus, the value bet on Valencia should appear
        wh_bets = [o for o in opps if o.bookmaker_id == wh.id]
        assert len(wh_bets) >= 1

    async def test_detect_updates_existing_opportunity(self, db_session: AsyncSession):
        """Running detection twice should update, not duplicate."""
        await self._setup_match_with_odds(db_session)

        detector = OpportunityDetectionService(min_value=0.01, min_bookmakers=3)
        await detector.detect_all(db_session)
        count1 = (await db_session.execute(select(Opportunity))).scalars().all()

        await detector.detect_all(db_session)
        count2 = (await db_session.execute(select(Opportunity))).scalars().all()

        # Same number of opportunities (updated, not duplicated)
        assert len(count1) == len(count2)

    async def test_batch_portfolio_caps_total_paper_exposure(
        self, db_session: AsyncSession
    ):
        """Múltiples matches con señales fuertes → PaperBets respetan el cap 20%."""
        from app.models.paper import PaperBet
        from app.services.paper_trading_service import (
            PAPER_MAX_TOTAL_EXPOSURE_UNITS,
        )

        await seed_database(db_session)
        commence = datetime.now(timezone.utc) + timedelta(days=1)
        # 6 matches diferentes, cada uno con señal fuerte (consenso a 3.50, soft a 4.20).
        teams = [(f"H{i}", f"A{i}") for i in range(6)]
        fake_data = []
        for h, a in teams:
            for bk in ("bet365", "pinnacle", "betfair_ex_eu", "marathonbet", "unibet_eu"):
                fake_data.append(
                    make_raw_odds(h, a, bk, [(h, 2.10), ("Draw", 3.30), (a, 3.50)], commence)
                )
            # Soft outlier con cuota notable en away
            fake_data.append(
                make_raw_odds(h, a, "williamhill", [(h, 2.10), ("Draw", 3.30), (a, 4.20)], commence)
            )
        await OddsIngestionService(FakeAdapter(fake_data)).ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_spain_la_liga"]
        )

        detector = OpportunityDetectionService(min_value=0.01, min_bookmakers=5)
        counts, _ = await detector.detect_all(db_session)
        assert counts["opportunities_found"] >= 6  # al menos 1 por match

        paper = (
            await db_session.execute(
                select(PaperBet).where(PaperBet.source_type == "value")
            )
        ).scalars().all()
        assert len(paper) > 0
        total_stake = sum(float(p.stake_units) for p in paper)
        assert total_stake <= float(PAPER_MAX_TOTAL_EXPOSURE_UNITS) + 1e-6

        # Ningún match debe tener más de un PaperBet (correlación: best leg only).
        match_ids = [p.match_id for p in paper]
        assert len(match_ids) == len(set(match_ids))

    async def test_expire_opportunities(self, db_session: AsyncSession):
        """Opportunities for past matches should be expired."""
        await seed_database(db_session)

        # Create odds for a match in the past
        past_time = datetime.now(timezone.utc) - timedelta(hours=2)
        fake_data = [
            make_raw_odds("Past Home", "Past Away", "bet365",
                          [("Past Home", 2.50), ("Draw", 3.10), ("Past Away", 3.00)],
                          past_time),
            make_raw_odds("Past Home", "Past Away", "pinnacle",
                          [("Past Home", 2.10), ("Draw", 3.25), ("Past Away", 3.55)],
                          past_time),
            make_raw_odds("Past Home", "Past Away", "betfair_ex_eu",
                          [("Past Home", 2.08), ("Draw", 3.35), ("Past Away", 3.65)],
                          past_time),
            make_raw_odds("Past Home", "Past Away", "williamhill",
                          [("Past Home", 2.05), ("Draw", 3.40), ("Past Away", 3.50)],
                          past_time),
        ]

        adapter = FakeAdapter(fake_data)
        service = OddsIngestionService(adapter)
        await service.ingest_odds(db_session, sport_key="football",
                                  league_keys=["soccer_spain_la_liga"])

        # Force match status to scheduled so detector scans it
        match_result = await db_session.execute(select(Match))
        match = match_result.scalar_one()
        match.status = "scheduled"
        await db_session.flush()

        # First detection should find opportunities
        detector = OpportunityDetectionService(min_value=0.01, min_bookmakers=3)
        # Since commence_time is in the past, detect_all won't find it
        # (query filters commence_time > now)
        # But we can test the expire logic separately

        # Manually create an opportunity that's expired
        outcome_result = await db_session.execute(select(Outcome).limit(1))
        outcome = outcome_result.scalar_one()
        bookmaker_result = await db_session.execute(select(Bookmaker).limit(1))
        bookmaker = bookmaker_result.scalar_one()

        opp = Opportunity(
            outcome_id=outcome.id,
            bookmaker_id=bookmaker.id,
            odds_price=Decimal("2.50"),
            consensus_prob=Decimal("0.45000"),
            implied_prob=Decimal("0.40000"),
            value_pct=Decimal("0.12500"),
            kelly_stake_pct=Decimal("0.05000"),
            expires_at=past_time,
        )
        db_session.add(opp)
        await db_session.flush()

        # Run detection — should expire the opportunity
        counts, _ = await detector.detect_all(db_session)
        assert counts.get("expired", 0) >= 1

        # Verify it's expired
        refreshed = await db_session.get(Opportunity, opp.id)
        assert refreshed.status == "expired"


class TestFullPipeline:
    async def test_seed_ingest_detect(self, db_session: AsyncSession):
        """Test completo: seed → ingest → detect → verify."""
        # 1. Seed
        seed_counts = await seed_database(db_session)
        assert seed_counts["sports"] > 0

        # 2. Ingest odds with value scenario
        commence = datetime.now(timezone.utc) + timedelta(days=1)
        fake_data = [
            make_raw_odds("Team A", "Team B", "bet365",
                          [("Team A", 2.10), ("Draw", 3.30), ("Team B", 3.60)], commence),
            make_raw_odds("Team A", "Team B", "pinnacle",
                          [("Team A", 2.12), ("Draw", 3.25), ("Team B", 3.55)], commence),
            make_raw_odds("Team A", "Team B", "betfair_ex_eu",
                          [("Team A", 2.08), ("Draw", 3.35), ("Team B", 3.65)], commence),
            # Bookmaker with outlier odds → value bet
            make_raw_odds("Team A", "Team B", "williamhill",
                          [("Team A", 2.60), ("Draw", 2.90), ("Team B", 2.80)], commence),
        ]

        adapter = FakeAdapter(fake_data)
        ingestion = OddsIngestionService(adapter)
        ingest_counts = await ingestion.ingest_odds(
            db_session, sport_key="football",
            league_keys=["soccer_spain_la_liga"],
        )
        assert ingest_counts["events"] == 1
        assert ingest_counts["errors"] == 0

        # 3. Detect
        detector = OpportunityDetectionService(min_value=0.01, min_bookmakers=3)
        detect_counts, new_opps = await detector.detect_all(db_session)
        assert detect_counts["errors"] == 0

        # 4. Verify opportunities exist
        opps_result = await db_session.execute(
            select(Opportunity).where(Opportunity.status == "active")
        )
        opportunities = opps_result.scalars().all()

        # WH odds are significantly different from consensus,
        # so there should be value bets
        assert len(opportunities) > 0

        # Each opportunity should have valid data
        for opp in opportunities:
            assert float(opp.value_pct) > 0
            assert float(opp.odds_price) > 1.0
            assert float(opp.consensus_prob) > 0
            assert float(opp.consensus_prob) < 1.0
            assert opp.expires_at is not None
