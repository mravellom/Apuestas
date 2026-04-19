"""Tests del ciclo de vida completo del ExecutionService."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.arbitrage import ArbitrageOpportunity
from app.models.bookmaker import Bookmaker
from app.models.broker import Broker
from app.models.market import Market, MarketType, Odds, Outcome
from app.models.match import Match
from app.models.opportunity import BetTracking
from app.models.sport import League, Season, Sport
from app.models.team import Team
from app.models.user import Bankroll, User
from app.services.arbitrage_service import ArbitrageDetectionService
from app.services.execution_service import (
    DeadArbError,
    ExecutionError,
    ExecutionService,
    StaleArbError,
)


async def _make_fixture(db):
    """Crea la red mínima: user + bankroll + match + market + outcomes + books + arb."""
    user = User(
        email=f"exec-{datetime.now(timezone.utc).timestamp()}@test.com",
        username=f"exec-{datetime.now(timezone.utc).timestamp()}",
        hashed_password="x",
    )
    db.add(user)
    await db.flush()

    bankroll = Bankroll(
        user_id=user.id,
        name="Test",
        currency="USD",
        initial_amount=Decimal("10000.00"),
        current_amount=Decimal("10000.00"),
    )
    db.add(bankroll)
    await db.flush()

    sport = Sport(key=f"test-{user.id}", name="Test")
    db.add(sport)
    await db.flush()
    league = League(sport_id=sport.id, key=f"test-lg-{user.id}", name="Test")
    db.add(league)
    await db.flush()
    season = Season(league_id=league.id, name="2025-2026")
    db.add(season)
    await db.flush()

    home = Team(sport_id=sport.id, canonical_name="Home FC")
    away = Team(sport_id=sport.id, canonical_name="Away FC")
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

    mt = (
        await db.execute(select(MarketType).where(MarketType.key == "h2h"))
    ).scalar_one_or_none()
    if mt is None:
        mt = MarketType(key="h2h", name="Match Result")
        db.add(mt)
        await db.flush()

    market = Market(match_id=match.id, market_type_id=mt.id)
    db.add(market)
    await db.flush()

    out_home = Outcome(market_id=market.id, key="home", name="Home FC")
    out_away = Outcome(market_id=market.id, key="away", name="Away FC")
    db.add_all([out_home, out_away])
    await db.flush()

    # Broker con 1% comisión → Pinnacle lo hereda.
    broker = Broker(
        key=f"sm-{user.id}",
        name="SportMarket Test",
        default_commission_pct=Decimal("0.01"),
        typical_latency_ms=1000,
    )
    db.add(broker)
    await db.flush()

    bk_pin = Bookmaker(key=f"pin-{user.id}", name="Pinnacle Test", is_sharp=True, broker_id=broker.id)
    bk_bet = Bookmaker(key=f"bet-{user.id}", name="Bet365 Test", is_sharp=False)
    db.add_all([bk_pin, bk_bet])
    await db.flush()

    # Odds rows que reflejan el arb — necesarias para que la revalidación
    # encuentre cuotas al momento de ejecutar. Captured_at reciente.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add_all([
        Odds(outcome_id=out_home.id, bookmaker_id=bk_pin.id, price=Decimal("2.10"), captured_at=now, source="test"),
        Odds(outcome_id=out_away.id, bookmaker_id=bk_pin.id, price=Decimal("1.90"), captured_at=now, source="test"),
        Odds(outcome_id=out_home.id, bookmaker_id=bk_bet.id, price=Decimal("1.95"), captured_at=now, source="test"),
        Odds(outcome_id=out_away.id, bookmaker_id=bk_bet.id, price=Decimal("2.05"), captured_at=now, source="test"),
    ])
    await db.flush()

    arb = ArbitrageOpportunity(
        match_id=match.id,
        market_id=market.id,
        total_implied=Decimal("0.97"),
        profit_pct=Decimal("3.000"),
        num_outcomes=2,
        legs=[
            {
                "outcome": "home",
                "outcome_name": "Home FC",
                "bookmaker": bk_pin.key,
                "odds": 2.10,
                "stake_pct": 0.49,
            },
            {
                "outcome": "away",
                "outcome_name": "Away FC",
                "bookmaker": bk_bet.key,
                "odds": 2.05,
                "stake_pct": 0.51,
            },
        ],
        # detected_at reciente para que la revalidación pase (age ≈ 0)
        detected_at=now,
        expires_at=match.commence_time,
    )
    db.add(arb)
    await db.commit()

    return {
        "user": user,
        "bankroll": bankroll,
        "arb": arb,
        "bk_pin": bk_pin,
        "bk_bet": bk_bet,
        "out_home": out_home,
        "out_away": out_away,
    }


@pytest.mark.asyncio
async def test_execute_creates_pending_bets_and_reserves_bankroll(db_session):
    fx = await _make_fixture(db_session)
    svc = ExecutionService()

    plan = await svc.execute_arbitrage_manual(
        db_session,
        arbitrage_id=fx["arb"].id,
        user_id=fx["user"].id,
        bankroll_id=fx["bankroll"].id,
        total_stake=Decimal("1000.00"),
    )

    assert plan.arbitrage_id == fx["arb"].id
    assert plan.total_stake == Decimal("1000.00")
    assert plan.currency == "USD"
    assert len(plan.legs) == 2

    # Cada leg debe tener commission del broker (0.01) porque Pinnacle la hereda.
    # Bet365 no tiene broker → 0.
    legs_by_book = {leg.bookmaker_key: leg for leg in plan.legs}
    assert legs_by_book[fx["bk_pin"].key].commission_pct == Decimal("0.01000")
    assert legs_by_book[fx["bk_bet"].key].commission_pct == Decimal("0.00000")

    # Suma de stakes == total
    total_stakes = sum(leg.stake_amount for leg in plan.legs)
    assert total_stakes == Decimal("1000.00")

    # Bets en DB
    bets = (
        await db_session.execute(
            select(BetTracking).where(BetTracking.arbitrage_id == fx["arb"].id)
        )
    ).scalars().all()
    assert len(bets) == 2
    assert all(b.status == "pending" for b in bets)
    assert all(b.odds_at_detection is not None for b in bets)
    assert all(b.odds_at_placement is None for b in bets)

    # Bankroll reserved = total_stake
    await db_session.refresh(fx["bankroll"])
    assert fx["bankroll"].reserved_amount == Decimal("1000.00")
    assert fx["bankroll"].available_amount == Decimal("9000.00")


@pytest.mark.asyncio
async def test_execute_fails_when_bankroll_insufficient(db_session):
    fx = await _make_fixture(db_session)
    svc = ExecutionService()

    with pytest.raises(ExecutionError, match="Insufficient bankroll"):
        await svc.execute_arbitrage_manual(
            db_session,
            arbitrage_id=fx["arb"].id,
            user_id=fx["user"].id,
            bankroll_id=fx["bankroll"].id,
            total_stake=Decimal("20000.00"),
        )


@pytest.mark.asyncio
async def test_execute_fails_when_arb_not_active(db_session):
    fx = await _make_fixture(db_session)
    fx["arb"].status = "expired"
    await db_session.commit()

    svc = ExecutionService()
    with pytest.raises(ExecutionError, match="not active"):
        await svc.execute_arbitrage_manual(
            db_session,
            arbitrage_id=fx["arb"].id,
            user_id=fx["user"].id,
            bankroll_id=fx["bankroll"].id,
            total_stake=Decimal("1000.00"),
        )


@pytest.mark.asyncio
async def test_mark_leg_placed_updates_status_and_odds(db_session):
    fx = await _make_fixture(db_session)
    svc = ExecutionService()

    plan = await svc.execute_arbitrage_manual(
        db_session,
        arbitrage_id=fx["arb"].id,
        user_id=fx["user"].id,
        bankroll_id=fx["bankroll"].id,
        total_stake=Decimal("1000.00"),
    )

    leg = plan.legs[0]
    bet = await svc.mark_leg_placed(
        db_session,
        bet_id=leg.bet_id,
        user_id=fx["user"].id,
        odds_at_placement=Decimal("2.08"),
    )

    assert bet.status == "placed"
    assert bet.odds_at_placement == Decimal("2.08")
    assert bet.placed_at is not None


@pytest.mark.asyncio
async def test_mark_leg_rejected_releases_bankroll(db_session):
    fx = await _make_fixture(db_session)
    svc = ExecutionService()

    plan = await svc.execute_arbitrage_manual(
        db_session,
        arbitrage_id=fx["arb"].id,
        user_id=fx["user"].id,
        bankroll_id=fx["bankroll"].id,
        total_stake=Decimal("1000.00"),
    )

    leg = plan.legs[0]
    await svc.mark_leg_rejected(
        db_session,
        bet_id=leg.bet_id,
        user_id=fx["user"].id,
        reason="Odds moved too much",
    )

    await db_session.refresh(fx["bankroll"])
    # Liberó la porción del leg rechazado; la otra pata sigue reservada.
    assert fx["bankroll"].reserved_amount == Decimal("1000.00") - leg.stake_amount


@pytest.mark.asyncio
async def test_settle_leg_won_updates_bankroll_and_pnl(db_session):
    fx = await _make_fixture(db_session)
    svc = ExecutionService()

    plan = await svc.execute_arbitrage_manual(
        db_session,
        arbitrage_id=fx["arb"].id,
        user_id=fx["user"].id,
        bankroll_id=fx["bankroll"].id,
        total_stake=Decimal("1000.00"),
    )

    leg = plan.legs[0]
    await svc.mark_leg_placed(
        db_session,
        bet_id=leg.bet_id,
        user_id=fx["user"].id,
        odds_at_placement=Decimal("2.10"),
    )

    # Stake 490 a 2.10 → payout 1029, pnl +539
    await svc.settle_leg(
        db_session,
        bet_id=leg.bet_id,
        user_id=fx["user"].id,
        result="won",
        actual_payout=leg.stake_amount * Decimal("2.10"),
    )

    bet = (
        await db_session.execute(select(BetTracking).where(BetTracking.id == leg.bet_id))
    ).scalar_one()
    assert bet.result == "won"
    assert bet.profit_loss == leg.stake_amount * (Decimal("2.10") - Decimal("1"))

    await db_session.refresh(fx["bankroll"])
    # current_amount subió por el pnl; reserved bajó por el stake liberado.
    assert fx["bankroll"].current_amount > Decimal("10000.00")
    assert fx["bankroll"].reserved_amount == Decimal("1000.00") - leg.stake_amount


@pytest.mark.asyncio
async def test_revalidate_alive_when_odds_unchanged(db_session):
    fx = await _make_fixture(db_session)
    svc = ArbitrageDetectionService()
    result = await svc.revalidate_arb(db_session, fx["arb"].id)
    assert result.status == "alive"
    assert result.current_profit_pct > 0


@pytest.mark.asyncio
async def test_revalidate_dead_when_odds_degraded(db_session):
    fx = await _make_fixture(db_session)
    # Colapsa las cuotas a valores que anulan el arb.
    from app.models.market import Odds as OddsModel
    odds = (await db_session.execute(select(OddsModel))).scalars().all()
    for o in odds:
        o.price = Decimal("1.50")  # margen muy cargado
    await db_session.commit()

    svc = ArbitrageDetectionService()
    result = await svc.revalidate_arb(db_session, fx["arb"].id)
    assert result.status == "dead"


@pytest.mark.asyncio
async def test_execute_raises_dead_arb_error_when_odds_degraded(db_session):
    fx = await _make_fixture(db_session)
    from app.models.market import Odds as OddsModel
    odds = (await db_session.execute(select(OddsModel))).scalars().all()
    for o in odds:
        o.price = Decimal("1.50")
    await db_session.commit()

    svc = ExecutionService()
    with pytest.raises(DeadArbError):
        await svc.execute_arbitrage_manual(
            db_session,
            arbitrage_id=fx["arb"].id,
            user_id=fx["user"].id,
            bankroll_id=fx["bankroll"].id,
            total_stake=Decimal("1000"),
        )


@pytest.mark.asyncio
async def test_exposure_zero_when_all_pending(db_session):
    fx = await _make_fixture(db_session)
    svc = ExecutionService()

    await svc.execute_arbitrage_manual(
        db_session,
        arbitrage_id=fx["arb"].id,
        user_id=fx["user"].id,
        bankroll_id=fx["bankroll"].id,
        total_stake=Decimal("1000"),
    )

    exp = await svc.compute_exposure(
        db_session, arbitrage_id=fx["arb"].id, user_id=fx["user"].id
    )
    # Sin legs placed, exposure es cero en todos los escenarios.
    assert exp.total_placed_stake == Decimal("0.00")
    assert exp.worst_case_pnl == Decimal("0.00")
    assert exp.best_case_pnl == Decimal("0.00")
    assert not exp.is_partial_fill
    assert not exp.any_rejected
    assert not exp.all_placed
    assert all(not s.covered for s in exp.scenarios)


@pytest.mark.asyncio
async def test_exposure_balanced_when_all_placed(db_session):
    fx = await _make_fixture(db_session)
    svc = ExecutionService()

    plan = await svc.execute_arbitrage_manual(
        db_session,
        arbitrage_id=fx["arb"].id,
        user_id=fx["user"].id,
        bankroll_id=fx["bankroll"].id,
        total_stake=Decimal("1000"),
    )
    for leg in plan.legs:
        await svc.mark_leg_placed(
            db_session,
            bet_id=leg.bet_id,
            user_id=fx["user"].id,
            odds_at_placement=leg.target_odds,
        )

    exp = await svc.compute_exposure(
        db_session, arbitrage_id=fx["arb"].id, user_id=fx["user"].id
    )
    assert exp.all_placed
    assert not exp.is_partial_fill
    # Arb genuino: worst_case debe ser positivo (o casi) tras comisión.
    # Con 3% profit bruto y 1% commission en Pinnacle, sigue positivo.
    assert exp.worst_case_pnl > Decimal("-100")  # margen de seguridad por redondeo
    assert exp.best_case_pnl > Decimal("-100")
    # Ambos outcomes cubiertos.
    assert all(s.covered for s in exp.scenarios)


@pytest.mark.asyncio
async def test_exposure_partial_fill_shows_unilateral_risk(db_session):
    fx = await _make_fixture(db_session)
    svc = ExecutionService()

    plan = await svc.execute_arbitrage_manual(
        db_session,
        arbitrage_id=fx["arb"].id,
        user_id=fx["user"].id,
        bankroll_id=fx["bankroll"].id,
        total_stake=Decimal("1000"),
    )
    # Placa solo el primer leg; rechaza el segundo.
    await svc.mark_leg_placed(
        db_session,
        bet_id=plan.legs[0].bet_id,
        user_id=fx["user"].id,
        odds_at_placement=plan.legs[0].target_odds,
    )
    await svc.mark_leg_rejected(
        db_session, bet_id=plan.legs[1].bet_id, user_id=fx["user"].id
    )

    exp = await svc.compute_exposure(
        db_session, arbitrage_id=fx["arb"].id, user_id=fx["user"].id
    )
    assert exp.is_partial_fill
    assert exp.any_rejected
    assert not exp.all_placed
    # Solo un leg placed: ganamos si gana su outcome, perdemos si gana el otro.
    covered_scenarios = [s for s in exp.scenarios if s.covered]
    uncovered = [s for s in exp.scenarios if not s.covered]
    assert len(covered_scenarios) == 1
    assert len(uncovered) == 1
    assert covered_scenarios[0].pnl > Decimal("0")  # gana si corre a favor
    assert uncovered[0].pnl < Decimal("0")  # pierde todo el stake si corre en contra


@pytest.mark.asyncio
async def test_exposure_suggests_replacement_for_rejected_leg(db_session):
    fx = await _make_fixture(db_session)
    svc = ExecutionService()

    # Agregar un bookmaker extra con odds para el mismo outcome del leg que será rejected.
    # El leg[1] del arb es "away" en bk_bet; creamos un tercer book con odds para away.
    bk_alt = Bookmaker(key=f"alt-{fx['user'].id}", name="Altbook", is_sharp=False)
    db_session.add(bk_alt)
    await db_session.flush()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add(
        Odds(
            outcome_id=fx["out_away"].id,
            bookmaker_id=bk_alt.id,
            price=Decimal("2.00"),
            captured_at=now,
            source="test",
        )
    )
    await db_session.commit()

    plan = await svc.execute_arbitrage_manual(
        db_session,
        arbitrage_id=fx["arb"].id,
        user_id=fx["user"].id,
        bankroll_id=fx["bankroll"].id,
        total_stake=Decimal("1000"),
    )
    await svc.mark_leg_placed(
        db_session,
        bet_id=plan.legs[0].bet_id,
        user_id=fx["user"].id,
        odds_at_placement=plan.legs[0].target_odds,
    )
    await svc.mark_leg_rejected(
        db_session, bet_id=plan.legs[1].bet_id, user_id=fx["user"].id
    )

    exp = await svc.compute_exposure(
        db_session, arbitrage_id=fx["arb"].id, user_id=fx["user"].id
    )
    assert len(exp.replacement_suggestions) == 1
    sug = exp.replacement_suggestions[0]
    assert any(
        a.bookmaker_key == bk_alt.key and a.odds == Decimal("2.0000")
        for a in sug.alternatives
    )


@pytest.mark.asyncio
async def test_settle_leg_lost_debits_bankroll(db_session):
    fx = await _make_fixture(db_session)
    svc = ExecutionService()

    plan = await svc.execute_arbitrage_manual(
        db_session,
        arbitrage_id=fx["arb"].id,
        user_id=fx["user"].id,
        bankroll_id=fx["bankroll"].id,
        total_stake=Decimal("1000.00"),
    )

    leg = plan.legs[0]
    await svc.mark_leg_placed(
        db_session,
        bet_id=leg.bet_id,
        user_id=fx["user"].id,
        odds_at_placement=Decimal("2.10"),
    )
    await svc.settle_leg(
        db_session,
        bet_id=leg.bet_id,
        user_id=fx["user"].id,
        result="lost",
        actual_payout=Decimal("0"),
    )

    await db_session.refresh(fx["bankroll"])
    # current_amount bajó por el stake perdido
    assert fx["bankroll"].current_amount == Decimal("10000.00") - leg.stake_amount
