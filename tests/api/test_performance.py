"""Tests API para /api/v1/performance/summary."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.models.bookmaker import Bookmaker
from app.models.market import Outcome
from app.models.opportunity import BetTracking
from app.models.user import Bankroll
from app.services.odds_service import OddsIngestionService
from app.services.seed_service import seed_database


class FakeAdapter(DataSourceAdapter):
    def __init__(self, data):
        self.odds_data = data

    async def fetch_odds(self, sport, regions=None, markets=None):
        return self.odds_data

    async def fetch_events(self, sport):
        return []


async def _seed_outcome_and_bookmaker(db):
    """Ensure there's at least one Outcome and Bookmaker to FK from bets."""
    await seed_database(db)

    commence = datetime.now(timezone.utc) + timedelta(days=1)
    data = [
        RawOddsData(
            source="test",
            sport_key="soccer_spain_la_liga",
            league_key="soccer_spain_la_liga",
            home_team="PH",
            away_team="PA",
            commence_time=commence,
            bookmaker="bet365",
            market_type="h2h",
            outcomes=[
                RawOutcome(name="PH", price=2.1),
                RawOutcome(name="Draw", price=3.3),
                RawOutcome(name="PA", price=3.6),
            ],
            external_id="perf_seed",
        )
    ]
    await OddsIngestionService(FakeAdapter(data)).ingest_odds(
        db, sport_key="football", league_keys=["soccer_spain_la_liga"]
    )

    from sqlalchemy import select
    outcome = (await db.execute(select(Outcome))).scalars().first()
    bookmaker = (await db.execute(select(Bookmaker))).scalars().first()
    return outcome, bookmaker


async def _make_bankroll(db, user_id):
    bankroll = Bankroll(
        user_id=user_id,
        name="Main",
        currency="EUR",
        initial_amount=Decimal("1000"),
        current_amount=Decimal("1000"),
    )
    db.add(bankroll)
    await db.flush()
    return bankroll


class TestPerformanceSummary:
    async def test_requires_auth(self, client):
        response = await client.get("/api/v1/performance/summary")
        assert response.status_code == 401

    async def test_no_bets_returns_zeros(self, client, auth_headers):
        response = await client.get(
            "/api/v1/performance/summary", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data == {
            "total_bets": 0,
            "won": 0,
            "lost": 0,
            "pending": 0,
            "win_rate": 0.0,
            "total_staked": 0.0,
            "total_profit": 0.0,
            "roi": 0.0,
        }

    async def test_aggregates_won_lost_pending(
        self, client, auth_headers, db_session, test_user
    ):
        outcome, bookmaker = await _seed_outcome_and_bookmaker(db_session)
        bankroll = await _make_bankroll(db_session, test_user.id)

        def bet(stake: str, result: str | None, pnl: str | None):
            return BetTracking(
                user_id=test_user.id,
                bankroll_id=bankroll.id,
                outcome_id=outcome.id,
                bookmaker_id=bookmaker.id,
                stake_amount=Decimal(stake),
                odds_at_placement=Decimal("2.10"),
                staking_method="flat",
                result=result,
                profit_loss=Decimal(pnl) if pnl is not None else None,
            )

        # 2 won (+100 each), 1 lost (-50), 1 pending
        db_session.add_all([
            bet("100", "won", "110"),
            bet("100", "won", "110"),
            bet("50", "lost", "-50"),
            bet("75", None, None),
        ])
        await db_session.commit()

        response = await client.get(
            "/api/v1/performance/summary", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()

        assert data["total_bets"] == 4
        assert data["won"] == 2
        assert data["lost"] == 1
        assert data["pending"] == 1
        # win_rate = 2 / (2+1) * 100 = 66.67
        assert data["win_rate"] == 66.67
        assert data["total_staked"] == 325.0  # 100+100+50+75
        assert data["total_profit"] == 170.0  # 110+110-50 (pending contributes 0)
        # roi = profit / staked * 100 = 170/325 * 100 ≈ 52.31
        assert data["roi"] == 52.31

    async def test_win_rate_is_zero_when_all_pending(
        self, client, auth_headers, db_session, test_user
    ):
        outcome, bookmaker = await _seed_outcome_and_bookmaker(db_session)
        bankroll = await _make_bankroll(db_session, test_user.id)

        db_session.add(
            BetTracking(
                user_id=test_user.id,
                bankroll_id=bankroll.id,
                outcome_id=outcome.id,
                bookmaker_id=bookmaker.id,
                stake_amount=Decimal("50"),
                odds_at_placement=Decimal("2.0"),
                staking_method="flat",
                result=None,
            )
        )
        await db_session.commit()

        response = await client.get(
            "/api/v1/performance/summary", headers=auth_headers
        )
        data = response.json()
        assert data["total_bets"] == 1
        assert data["win_rate"] == 0.0
        assert data["roi"] == 0.0

    async def test_isolation_between_users(
        self, client, auth_headers, db_session, test_user, premium_user
    ):
        """A user's summary must not include another user's bets."""
        outcome, bookmaker = await _seed_outcome_and_bookmaker(db_session)
        bankroll_free = await _make_bankroll(db_session, test_user.id)
        bankroll_premium = await _make_bankroll(db_session, premium_user.id)

        db_session.add_all([
            BetTracking(
                user_id=test_user.id,
                bankroll_id=bankroll_free.id,
                outcome_id=outcome.id,
                bookmaker_id=bookmaker.id,
                stake_amount=Decimal("10"),
                odds_at_placement=Decimal("2.0"),
                staking_method="flat",
                result="won",
                profit_loss=Decimal("10"),
            ),
            BetTracking(
                user_id=premium_user.id,
                bankroll_id=bankroll_premium.id,
                outcome_id=outcome.id,
                bookmaker_id=bookmaker.id,
                stake_amount=Decimal("500"),
                odds_at_placement=Decimal("3.0"),
                staking_method="flat",
                result="won",
                profit_loss=Decimal("1000"),
            ),
        ])
        await db_session.commit()

        response = await client.get(
            "/api/v1/performance/summary", headers=auth_headers
        )
        data = response.json()
        assert data["total_bets"] == 1
        assert data["total_staked"] == 10.0
        assert data["total_profit"] == 10.0
