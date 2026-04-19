"""Tests de los endpoints de ejecución manual de arbitrajes."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.arbitrage import ArbitrageOpportunity
from app.models.bookmaker import Bookmaker
from app.models.market import Market, MarketType, Odds, Outcome
from app.models.match import Match
from app.models.opportunity import BetTracking
from app.models.sport import League, Season, Sport
from app.models.team import Team
from app.models.user import Bankroll


async def _seed_arb_and_bankroll(db, user_id):
    sport = Sport(key=f"sp-{user_id}", name="Test")
    db.add(sport)
    await db.flush()
    league = League(sport_id=sport.id, key=f"lg-{user_id}", name="Test")
    db.add(league)
    await db.flush()
    season = Season(league_id=league.id, name="2025-2026")
    db.add(season)
    await db.flush()

    home = Team(sport_id=sport.id, canonical_name="A")
    away = Team(sport_id=sport.id, canonical_name="B")
    db.add_all([home, away])
    await db.flush()

    match = Match(
        season_id=season.id,
        home_team_id=home.id,
        away_team_id=away.id,
        commence_time=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=6),
    )
    db.add(match)
    await db.flush()

    mt = (await db.execute(select(MarketType).where(MarketType.key == "h2h"))).scalar_one_or_none()
    if not mt:
        mt = MarketType(key="h2h", name="Match Result")
        db.add(mt)
        await db.flush()

    market = Market(match_id=match.id, market_type_id=mt.id)
    db.add(market)
    await db.flush()

    o1 = Outcome(market_id=market.id, key="home", name="A")
    o2 = Outcome(market_id=market.id, key="away", name="B")
    db.add_all([o1, o2])
    await db.flush()

    b1 = Bookmaker(key=f"b1-{user_id}", name="B1", is_sharp=False)
    b2 = Bookmaker(key=f"b2-{user_id}", name="B2", is_sharp=False)
    db.add_all([b1, b2])
    await db.flush()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add_all([
        Odds(outcome_id=o1.id, bookmaker_id=b1.id, price=Decimal("2.10"), captured_at=now, source="test"),
        Odds(outcome_id=o2.id, bookmaker_id=b1.id, price=Decimal("1.90"), captured_at=now, source="test"),
        Odds(outcome_id=o1.id, bookmaker_id=b2.id, price=Decimal("1.95"), captured_at=now, source="test"),
        Odds(outcome_id=o2.id, bookmaker_id=b2.id, price=Decimal("2.05"), captured_at=now, source="test"),
    ])
    await db.flush()

    arb = ArbitrageOpportunity(
        match_id=match.id,
        market_id=market.id,
        total_implied=Decimal("0.98"),
        profit_pct=Decimal("2.000"),
        num_outcomes=2,
        legs=[
            {"outcome": "home", "outcome_name": "A", "bookmaker": b1.key, "odds": 2.1, "stake_pct": 0.5},
            {"outcome": "away", "outcome_name": "B", "bookmaker": b2.key, "odds": 2.05, "stake_pct": 0.5},
        ],
        detected_at=now,
        expires_at=match.commence_time,
    )
    db.add(arb)

    bankroll = Bankroll(
        user_id=user_id,
        name="Test",
        currency="USD",
        initial_amount=Decimal("5000"),
        current_amount=Decimal("5000"),
    )
    db.add(bankroll)
    await db.commit()

    return {"arb": arb, "bankroll": bankroll}


class TestExecuteArbitrage:
    async def test_creates_pending_bets(self, client, auth_headers, db_session, test_user):
        fx = await _seed_arb_and_bankroll(db_session, test_user.id)

        r = await client.post(
            f"/api/v1/arbitrage/{fx['arb'].id}/execute",
            headers=auth_headers,
            json={"bankroll_id": fx["bankroll"].id, "total_stake": 1000.0},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["arbitrage_id"] == fx["arb"].id
        assert body["currency"] == "USD"
        assert len(body["legs"]) == 2
        assert all(leg["bet_id"] > 0 for leg in body["legs"])
        assert all(leg["min_acceptable_odds"] < leg["target_odds"] for leg in body["legs"])

    async def test_rejects_when_insufficient_bankroll(
        self, client, auth_headers, db_session, test_user
    ):
        fx = await _seed_arb_and_bankroll(db_session, test_user.id)
        r = await client.post(
            f"/api/v1/arbitrage/{fx['arb'].id}/execute",
            headers=auth_headers,
            json={"bankroll_id": fx["bankroll"].id, "total_stake": 999999},
        )
        assert r.status_code == 400
        assert "Insufficient bankroll" in r.json()["detail"]

    async def test_rejects_unauthenticated(self, client):
        r = await client.post(
            "/api/v1/arbitrage/1/execute",
            json={"bankroll_id": 1, "total_stake": 100.0},
        )
        assert r.status_code == 401


class TestBetLifecycle:
    async def test_place_then_settle_won(
        self, client, auth_headers, db_session, test_user
    ):
        fx = await _seed_arb_and_bankroll(db_session, test_user.id)
        r = await client.post(
            f"/api/v1/arbitrage/{fx['arb'].id}/execute",
            headers=auth_headers,
            json={"bankroll_id": fx["bankroll"].id, "total_stake": 1000.0},
        )
        assert r.status_code == 201
        bet_id = r.json()["legs"][0]["bet_id"]

        # place
        r = await client.patch(
            f"/api/v1/bets/{bet_id}/place",
            headers=auth_headers,
            json={"odds_at_placement": 2.08},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "placed"
        assert float(r.json()["odds_at_placement"]) == 2.08

        # settle won
        r = await client.patch(
            f"/api/v1/bets/{bet_id}/settle",
            headers=auth_headers,
            json={"result": "won", "actual_payout": 1040.0},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["result"] == "won"
        assert body["profit_loss"] == 540.0  # 1040 - 500 stake

    async def test_reject_releases_reserve(
        self, client, auth_headers, db_session, test_user
    ):
        fx = await _seed_arb_and_bankroll(db_session, test_user.id)
        r = await client.post(
            f"/api/v1/arbitrage/{fx['arb'].id}/execute",
            headers=auth_headers,
            json={"bankroll_id": fx["bankroll"].id, "total_stake": 1000.0},
        )
        bet_id = r.json()["legs"][0]["bet_id"]

        r = await client.patch(
            f"/api/v1/bets/{bet_id}/reject",
            headers=auth_headers,
            json={"reason": "Odds moved"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"

    async def test_cannot_place_another_users_bet(
        self, client, auth_headers, db_session, test_user, premium_user
    ):
        fx = await _seed_arb_and_bankroll(db_session, premium_user.id)
        # Crear bet directamente con user_id del premium
        bet = BetTracking(
            user_id=premium_user.id,
            arbitrage_id=fx["arb"].id,
            bankroll_id=fx["bankroll"].id,
            outcome_id=1,
            bookmaker_id=1,
            stake_amount=Decimal("100"),
            odds_at_detection=Decimal("2.0"),
            staking_method="arbitrage",
            status="pending",
        )
        db_session.add(bet)
        await db_session.commit()

        # test_user intenta tocarlo
        r = await client.patch(
            f"/api/v1/bets/{bet.id}/place",
            headers=auth_headers,
            json={"odds_at_placement": 2.0},
        )
        assert r.status_code == 400
        assert "not owned" in r.json()["detail"]


class TestListBets:
    async def test_list_filters_by_user(self, client, auth_headers, db_session, test_user):
        fx = await _seed_arb_and_bankroll(db_session, test_user.id)
        await client.post(
            f"/api/v1/arbitrage/{fx['arb'].id}/execute",
            headers=auth_headers,
            json={"bankroll_id": fx["bankroll"].id, "total_stake": 1000.0},
        )
        r = await client.get("/api/v1/bets", headers=auth_headers)
        assert r.status_code == 200
        bets = r.json()
        assert len(bets) == 2
        assert all(b["status"] == "pending" for b in bets)

    async def test_list_filtered_by_status(
        self, client, auth_headers, db_session, test_user
    ):
        fx = await _seed_arb_and_bankroll(db_session, test_user.id)
        r = await client.post(
            f"/api/v1/arbitrage/{fx['arb'].id}/execute",
            headers=auth_headers,
            json={"bankroll_id": fx["bankroll"].id, "total_stake": 1000.0},
        )
        bet_id = r.json()["legs"][0]["bet_id"]
        await client.patch(
            f"/api/v1/bets/{bet_id}/place",
            headers=auth_headers,
            json={"odds_at_placement": 2.0},
        )

        r = await client.get("/api/v1/bets?status_filter=placed", headers=auth_headers)
        assert r.status_code == 200
        assert len(r.json()) == 1
