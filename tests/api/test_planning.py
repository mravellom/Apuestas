"""Tests del planificador diario."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.arbitrage import ArbitrageOpportunity
from app.models.bookmaker import Bookmaker
from app.models.market import Market, MarketType, Outcome
from app.models.match import Match
from app.models.sport import League, Season, Sport
from app.models.team import Team
from app.models.user import Bankroll


async def _seed_arbs(db, user_id, arb_specs: list[dict]):
    """arb_specs: list of {"profit_pct": float, "books": [str, str]}."""
    sport = Sport(key=f"sp-{user_id}", name="Test")
    db.add(sport)
    await db.flush()
    league = League(sport_id=sport.id, key=f"lg-{user_id}", name="Test")
    db.add(league)
    await db.flush()
    season = Season(league_id=league.id, name="2025-2026")
    db.add(season)
    await db.flush()

    mt = (await db.execute(select(MarketType).where(MarketType.key == "h2h"))).scalar_one_or_none()
    if mt is None:
        mt = MarketType(key="h2h", name="Match Result")
        db.add(mt)
        await db.flush()

    arbs_created = []
    for i, spec in enumerate(arb_specs):
        home = Team(sport_id=sport.id, canonical_name=f"HomeTeam{i}")
        away = Team(sport_id=sport.id, canonical_name=f"AwayTeam{i}")
        db.add_all([home, away])
        await db.flush()

        match = Match(
            season_id=season.id,
            home_team_id=home.id,
            away_team_id=away.id,
            commence_time=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=6 + i),
        )
        db.add(match)
        await db.flush()

        market = Market(match_id=match.id, market_type_id=mt.id)
        db.add(market)
        await db.flush()

        out_home = Outcome(market_id=market.id, key="home", name=f"HomeTeam{i}")
        out_away = Outcome(market_id=market.id, key="away", name=f"AwayTeam{i}")
        db.add_all([out_home, out_away])
        await db.flush()

        for bk_key in spec["books"]:
            existing = (
                await db.execute(select(Bookmaker).where(Bookmaker.key == bk_key))
            ).scalar_one_or_none()
            if existing is None:
                db.add(Bookmaker(key=bk_key, name=bk_key.title(), is_sharp=False))
        await db.flush()

        arb = ArbitrageOpportunity(
            match_id=match.id,
            market_id=market.id,
            total_implied=Decimal("0.98"),
            profit_pct=Decimal(str(spec["profit_pct"])),
            num_outcomes=2,
            legs=[
                {"outcome": "home", "outcome_name": f"HomeTeam{i}", "bookmaker": spec["books"][0], "odds": 2.0, "stake_pct": 0.5},
                {"outcome": "away", "outcome_name": f"AwayTeam{i}", "bookmaker": spec["books"][1], "odds": 2.0, "stake_pct": 0.5},
            ],
            expires_at=match.commence_time,
        )
        db.add(arb)
        arbs_created.append(arb)

    bankroll = Bankroll(
        user_id=user_id,
        name="Test",
        currency="USD",
        initial_amount=Decimal("10000"),
        current_amount=Decimal("10000"),
    )
    db.add(bankroll)
    await db.commit()

    return {"bankroll": bankroll, "arbs": arbs_created}


class TestDailyPlanner:
    async def test_empty_when_no_arbs(self, client, auth_headers, db_session, test_user):
        fx = await _seed_arbs(db_session, test_user.id, [])
        r = await client.get(
            f"/api/v1/planning/daily?bankroll_id={fx['bankroll'].id}&daily_cap=1000",
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "empty"
        assert body["available_arbs"] == 0
        assert body["allocations"] == []

    async def test_single_arb_covers_target(
        self, client, auth_headers, db_session, test_user
    ):
        # Arb 2%, target 1% de 1000 = $10 → 1 arb con stake 500 = $10 profit
        fx = await _seed_arbs(db_session, test_user.id, [
            {"profit_pct": 2.0, "books": ["pinnacle", "bet365"]},
        ])
        r = await client.get(
            f"/api/v1/planning/daily?bankroll_id={fx['bankroll'].id}"
            f"&daily_cap=1000&target_pct=1.0&max_stake_per_arb_pct=100",
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "achievable"
        assert body["target_profit"] == 10.0
        assert body["expected_total_profit"] >= 10.0
        assert len(body["allocations"]) == 1
        assert body["allocations"][0]["profit_pct"] == 2.0

    async def test_shortfall_when_arbs_insufficient(
        self, client, auth_headers, db_session, test_user
    ):
        # 2 arbs de 0.5% cada uno, target 2% — insuficiente aunque stakee todo el cap
        fx = await _seed_arbs(db_session, test_user.id, [
            {"profit_pct": 0.5, "books": ["a", "b"]},
            {"profit_pct": 0.5, "books": ["c", "d"]},
        ])
        r = await client.get(
            f"/api/v1/planning/daily?bankroll_id={fx['bankroll'].id}"
            f"&daily_cap=1000&target_pct=2.0&max_stake_per_arb_pct=100",
            headers=auth_headers,
        )
        body = r.json()
        assert body["status"] == "unachievable"
        assert body["target_coverage_pct"] < 100
        assert "Faltan" in body["recommendation"]

    async def test_max_per_arb_caps_allocation(
        self, client, auth_headers, db_session, test_user
    ):
        # max_stake_per_arb_pct=10 → cada arb max 100 de 1000 cap.
        # 3 arbs grandes, pero el cap por arb limita.
        fx = await _seed_arbs(db_session, test_user.id, [
            {"profit_pct": 3.0, "books": ["a", "b"]},
            {"profit_pct": 2.0, "books": ["c", "d"]},
            {"profit_pct": 1.0, "books": ["e", "f"]},
        ])
        r = await client.get(
            f"/api/v1/planning/daily?bankroll_id={fx['bankroll'].id}"
            f"&daily_cap=1000&target_pct=1.0&max_stake_per_arb_pct=10",
            headers=auth_headers,
        )
        body = r.json()
        # Cada allocation no puede exceder 100 (10% de 1000)
        for a in body["allocations"]:
            assert a["suggested_stake"] <= 100.0 + 0.01  # tolerance

    async def test_arbs_sorted_by_profit_desc(
        self, client, auth_headers, db_session, test_user
    ):
        fx = await _seed_arbs(db_session, test_user.id, [
            {"profit_pct": 1.0, "books": ["a", "b"]},
            {"profit_pct": 3.0, "books": ["c", "d"]},
            {"profit_pct": 2.0, "books": ["e", "f"]},
        ])
        r = await client.get(
            f"/api/v1/planning/daily?bankroll_id={fx['bankroll'].id}"
            f"&daily_cap=10000&target_pct=10.0&max_stake_per_arb_pct=20",
            headers=auth_headers,
        )
        body = r.json()
        profits = [a["profit_pct"] for a in body["allocations"]]
        assert profits == sorted(profits, reverse=True)
        assert profits[0] == 3.0

    async def test_requires_ownership_of_bankroll(
        self, client, auth_headers, db_session, premium_user
    ):
        # Bankroll de otro user
        fx = await _seed_arbs(db_session, premium_user.id, [])
        r = await client.get(
            f"/api/v1/planning/daily?bankroll_id={fx['bankroll'].id}&daily_cap=100",
            headers=auth_headers,
        )
        assert r.status_code == 400
        assert "not owned" in r.json()["detail"].lower() or "not found" in r.json()["detail"].lower()

    async def test_unauthenticated_rejected(self, client):
        r = await client.get("/api/v1/planning/daily?bankroll_id=1&daily_cap=100")
        assert r.status_code == 401

    async def test_uses_config_defaults_when_params_absent(
        self, client, auth_headers, db_session, test_user
    ):
        """Sin target_pct en query, usa user_config.default_daily_target_pct."""
        fx = await _seed_arbs(db_session, test_user.id, [
            {"profit_pct": 1.5, "books": ["a", "b"]},
        ])
        r = await client.get(
            f"/api/v1/planning/daily?bankroll_id={fx['bankroll'].id}&daily_cap=1000",
            headers=auth_headers,
        )
        body = r.json()
        # Default target pct = 1.0 → target profit = 10.0
        assert body["target_pct"] == 1.0
        assert body["target_profit"] == 10.0
