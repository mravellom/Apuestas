from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DB, CurrentUser
from app.core.staking.factory import get_strategy
from app.database import get_db
from app.models.bookmaker import Bookmaker
from app.models.market import Market, MarketType, Outcome
from app.models.match import Match
from app.models.opportunity import BetTracking, Opportunity
from app.models.sport import League, Season, Sport
from app.models.team import Team
from app.models.user import Bankroll, UserConfig
from app.schemas.opportunity import (
    OpportunityDetailResponse,
    OpportunityResponse,
    TakeOpportunityRequest,
    TakeOpportunityResponse,
)


OpportunityStatus = Literal["active", "expired"]


class OpportunityHistoryItem(BaseModel):
    id: int
    match: str
    sport: str
    league: str
    commence_time: str
    market_type: str
    outcome_name: str
    bookmaker: str
    odds_price: float
    value_pct: float
    kelly_stake_pct: float | None
    status: OpportunityStatus
    detected_at: str
    closed_at: str | None

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


async def _build_opportunity_response(opp: Opportunity, db) -> OpportunityResponse:
    """Builds response by loading related entities."""
    outcome = await db.get(Outcome, opp.outcome_id)
    market = await db.get(Market, outcome.market_id)
    market_type = await db.get(MarketType, market.market_type_id)
    match = await db.get(Match, market.match_id)
    home_team = await db.get(Team, match.home_team_id)
    away_team = await db.get(Team, match.away_team_id)
    bookmaker = await db.get(Bookmaker, opp.bookmaker_id)

    return OpportunityResponse(
        id=opp.id,
        match_home_team=home_team.canonical_name,
        match_away_team=away_team.canonical_name,
        commence_time=match.commence_time,
        market_type=market_type.key,
        outcome_name=outcome.name,
        bookmaker_name=bookmaker.name,
        odds_price=float(opp.odds_price),
        consensus_prob=float(opp.consensus_prob),
        implied_prob=float(opp.implied_prob),
        value_pct=float(opp.value_pct),
        kelly_stake_pct=float(opp.kelly_stake_pct) if opp.kelly_stake_pct else None,
        is_steam=bool(opp.is_steam),
        status=opp.status,
        detected_at=opp.detected_at,
    )


@router.get("", response_model=list[OpportunityResponse])
async def list_opportunities(
    db: DB,
    user: CurrentUser,
    min_value: float | None = Query(None, ge=0),
    market_type: str | None = None,
    bookmaker: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = select(Opportunity).where(Opportunity.status == "active")

    if min_value is not None:
        query = query.where(Opportunity.value_pct >= min_value)

    query = query.order_by(Opportunity.value_pct.desc())

    # Free users: top 5 per day
    if user.role == "free":
        query = query.limit(5)
    else:
        query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    opportunities = result.scalars().all()

    return [await _build_opportunity_response(opp, db) for opp in opportunities]


@router.get("/history", response_model=list[OpportunityHistoryItem])
async def opportunities_history(
    status: str | None = None,
    limit: int = 200,
    from_date: date | None = Query(None, description="Filter detected_at >= from_date (UTC)"),
    to_date: date | None = Query(None, description="Filter detected_at <= to_date end-of-day (UTC)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Historial completo de value bets (todos los estados por defecto).
    Sin auth, mismo patrón que /arbitrage/history. Incluye sport/league
    para colorear en la UI.
    """
    limit = max(1, min(limit, 500))

    query = (
        select(Opportunity)
        .order_by(Opportunity.detected_at.desc())
        .limit(limit)
    )
    if status:
        query = query.where(Opportunity.status == status)
    if from_date:
        query = query.where(
            Opportunity.detected_at >= datetime.combine(from_date, datetime.min.time())
        )
    if to_date:
        query = query.where(
            Opportunity.detected_at < datetime.combine(to_date + timedelta(days=1), datetime.min.time())
        )

    result = (await db.execute(query)).scalars().all()

    response = []
    for opp in result:
        outcome = await db.get(Outcome, opp.outcome_id)
        market = await db.get(Market, outcome.market_id)
        market_type = await db.get(MarketType, market.market_type_id)
        match = await db.get(Match, market.match_id)
        home = await db.get(Team, match.home_team_id)
        away = await db.get(Team, match.away_team_id)
        bookmaker = await db.get(Bookmaker, opp.bookmaker_id)
        season = await db.get(Season, match.season_id)
        league = await db.get(League, season.league_id)
        sport = await db.get(Sport, league.sport_id)

        response.append(OpportunityHistoryItem(
            id=opp.id,
            match=f"{home.canonical_name} vs {away.canonical_name}",
            sport=sport.key,
            league=league.key,
            commence_time=match.commence_time.strftime("%Y-%m-%d %H:%M UTC"),
            market_type=market_type.key,
            outcome_name=outcome.name,
            bookmaker=bookmaker.key,
            odds_price=float(opp.odds_price),
            value_pct=float(opp.value_pct),
            kelly_stake_pct=float(opp.kelly_stake_pct) if opp.kelly_stake_pct else None,
            status=opp.status,
            detected_at=opp.detected_at.strftime("%Y-%m-%d %H:%M UTC"),
            closed_at=opp.closed_at.strftime("%Y-%m-%d %H:%M UTC") if opp.closed_at else None,
        ))

    return response


@router.get("/{opportunity_id}", response_model=OpportunityDetailResponse)
async def get_opportunity(opportunity_id: int, db: DB, user: CurrentUser):
    opp = await db.get(Opportunity, opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    base = await _build_opportunity_response(opp, db)

    # Calculate recommended stake based on user config
    config_result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user.id)
    )
    config = config_result.scalar_one_or_none()

    recommended_stake = None
    staking_method = None
    bankroll_used = None

    if config:
        bankroll_result = await db.execute(
            select(Bankroll).where(Bankroll.user_id == user.id).limit(1)
        )
        bankroll = bankroll_result.scalar_one_or_none()
        if bankroll:
            kwargs = {}
            if config.default_staking == "fractional_kelly":
                kwargs["fraction"] = float(config.kelly_fraction)
            elif config.default_staking == "flat":
                kwargs["flat_pct"] = float(config.flat_stake_pct) / 100

            strategy = get_strategy(config.default_staking, **kwargs)
            recommended_stake = strategy.calculate_stake(
                bankroll=float(bankroll.current_amount),
                odds=float(opp.odds_price),
                probability=float(opp.consensus_prob),
                max_stake_pct=float(config.max_stake_pct) / 100,
            )
            staking_method = config.default_staking
            bankroll_used = float(bankroll.current_amount)

    return OpportunityDetailResponse(
        **base.model_dump(),
        recommended_stake=recommended_stake,
        staking_method=staking_method,
        bankroll_used=bankroll_used,
    )


@router.post("/{opportunity_id}/take", response_model=TakeOpportunityResponse)
async def take_opportunity(
    opportunity_id: int, request: TakeOpportunityRequest, db: DB, user: CurrentUser
):
    opp = await db.get(Opportunity, opportunity_id)
    if not opp or opp.status != "active":
        raise HTTPException(status_code=404, detail="Active opportunity not found")

    bankroll = await db.get(Bankroll, request.bankroll_id)
    if not bankroll or bankroll.user_id != user.id:
        raise HTTPException(status_code=404, detail="Bankroll not found")

    # Get user config for staking
    config_result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user.id)
    )
    config = config_result.scalar_one_or_none()

    staking_method = request.staking_method or (config.default_staking if config else "flat")

    kwargs = {}
    if staking_method == "fractional_kelly" and config:
        kwargs["fraction"] = float(config.kelly_fraction)
    elif staking_method == "flat" and config:
        kwargs["flat_pct"] = float(config.flat_stake_pct) / 100

    strategy = get_strategy(staking_method, **kwargs)
    max_pct = float(config.max_stake_pct) / 100 if config else 0.05
    stake_amount = strategy.calculate_stake(
        bankroll=float(bankroll.current_amount),
        odds=float(opp.odds_price),
        probability=float(opp.consensus_prob),
        max_stake_pct=max_pct,
    )

    bet = BetTracking(
        user_id=user.id,
        opportunity_id=opp.id,
        bankroll_id=bankroll.id,
        outcome_id=opp.outcome_id,
        bookmaker_id=opp.bookmaker_id,
        stake_amount=Decimal(str(stake_amount)),
        odds_at_placement=opp.odds_price,
        staking_method=staking_method,
    )
    db.add(bet)

    # Deduct from bankroll
    bankroll.current_amount -= Decimal(str(stake_amount))
    await db.flush()

    return TakeOpportunityResponse(
        bet_id=bet.id,
        stake_amount=stake_amount,
        odds_at_placement=float(opp.odds_price),
        staking_method=staking_method,
    )
