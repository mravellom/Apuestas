from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from app.api.deps import DB, CurrentUser
from app.models.bookmaker import Bookmaker
from app.models.market import Market, Odds, Outcome
from app.models.match import Match
from app.models.sport import League, Season, Sport
from app.schemas.match import (
    MatchDetailResponse,
    MatchResponse,
    MarketResponse,
    OddsResponse,
    OutcomeResponse,
    TeamBrief,
)

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("", response_model=list[MatchResponse])
async def list_matches(
    db: DB,
    _user: CurrentUser,
    sport: str | None = None,
    league: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = select(Match).options(
        joinedload(Match.home_team),
        joinedload(Match.away_team),
    )

    if sport:
        query = query.join(Season).join(League).join(Sport).where(Sport.key == sport)
    if league:
        if not sport:
            query = query.join(Season).join(League)
        query = query.where(League.key == league)
    if status:
        query = query.where(Match.status == status)
    if date_from:
        query = query.where(Match.commence_time >= date_from)
    if date_to:
        query = query.where(Match.commence_time <= date_to)

    query = query.order_by(Match.commence_time).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    matches = result.unique().scalars().all()

    return [
        MatchResponse(
            id=m.id,
            external_id=m.external_id,
            commence_time=m.commence_time,
            status=m.status,
            home_score=m.home_score,
            away_score=m.away_score,
            home_team=TeamBrief(id=m.home_team.id, canonical_name=m.home_team.canonical_name),
            away_team=TeamBrief(id=m.away_team.id, canonical_name=m.away_team.canonical_name),
        )
        for m in matches
    ]


@router.get("/{match_id}", response_model=MatchDetailResponse)
async def get_match(match_id: int, db: DB, _user: CurrentUser):
    result = await db.execute(
        select(Match)
        .options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            selectinload(Match.markets)
            .joinedload(Market.market_type),
        )
        .where(Match.id == match_id)
    )
    match = result.unique().scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    # Load outcomes for each market
    market_ids = [m.id for m in match.markets]
    outcomes_result = await db.execute(
        select(Outcome).where(Outcome.market_id.in_(market_ids)) if market_ids else select(Outcome).where(False)
    )
    outcomes_by_market: dict[int, list[Outcome]] = {}
    for o in outcomes_result.scalars().all():
        outcomes_by_market.setdefault(o.market_id, []).append(o)

    markets = [
        MarketResponse(
            id=m.id,
            market_type_key=m.market_type.key,
            market_type_name=m.market_type.name,
            parameter=float(m.parameter) if m.parameter else None,
            outcomes=[
                OutcomeResponse(id=o.id, key=o.key, name=o.name)
                for o in outcomes_by_market.get(m.id, [])
            ],
        )
        for m in match.markets
    ]

    return MatchDetailResponse(
        id=match.id,
        external_id=match.external_id,
        commence_time=match.commence_time,
        status=match.status,
        home_score=match.home_score,
        away_score=match.away_score,
        home_team=TeamBrief(id=match.home_team.id, canonical_name=match.home_team.canonical_name),
        away_team=TeamBrief(id=match.away_team.id, canonical_name=match.away_team.canonical_name),
        season_id=match.season_id,
        markets=markets,
    )


@router.get("/{match_id}/odds", response_model=list[OddsResponse])
async def get_match_odds(match_id: int, db: DB, _user: CurrentUser):
    """Obtiene las últimas cuotas de todos los bookmakers para un partido."""
    # Verify match exists
    match_result = await db.execute(select(Match.id).where(Match.id == match_id))
    if not match_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Match not found")

    # Get latest odds per outcome+bookmaker using a subquery
    from sqlalchemy import func

    latest_subq = (
        select(
            Odds.outcome_id,
            Odds.bookmaker_id,
            func.max(Odds.captured_at).label("max_captured"),
        )
        .join(Outcome)
        .join(Market)
        .where(Market.match_id == match_id)
        .group_by(Odds.outcome_id, Odds.bookmaker_id)
        .subquery()
    )

    result = await db.execute(
        select(Odds, Outcome, Bookmaker)
        .join(Outcome, Odds.outcome_id == Outcome.id)
        .join(Bookmaker, Odds.bookmaker_id == Bookmaker.id)
        .join(
            latest_subq,
            (Odds.outcome_id == latest_subq.c.outcome_id)
            & (Odds.bookmaker_id == latest_subq.c.bookmaker_id)
            & (Odds.captured_at == latest_subq.c.max_captured),
        )
        .order_by(Outcome.id, Bookmaker.name)
    )

    return [
        OddsResponse(
            outcome_id=odds.outcome_id,
            outcome_key=outcome.key,
            outcome_name=outcome.name,
            bookmaker_key=bookmaker.key,
            bookmaker_name=bookmaker.name,
            price=float(odds.price),
            captured_at=odds.captured_at,
        )
        for odds, outcome, bookmaker in result.all()
    ]
