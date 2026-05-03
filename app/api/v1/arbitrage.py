"""Endpoints de arbitraje."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.arbitrage import ArbitrageOpportunity
from app.models.match import Match
from app.models.market import Market, MarketType
from app.models.team import Team
from app.services.arbitrage_service import ArbitrageDetectionService

router = APIRouter(prefix="/arbitrage", tags=["arbitrage"])


# Estado de un arb en la tabla `arbitrage_opportunities`. Drift contra la DB
# explota acá vía Pydantic validación — signal, no ruido.
ArbStatus = Literal["active", "expired", "dead"]
RevalidationStatus = Literal["alive", "stale", "dead"]


class ArbLegResponse(BaseModel):
    """Forma exacta de cada leg almacenada en `arb.legs` (JSON column)."""
    outcome: str
    outcome_name: str
    bookmaker: str
    odds: float
    stake_pct: float


class RevalidationResponse(BaseModel):
    status: RevalidationStatus
    detected_profit_pct: float
    current_profit_pct: float
    age_seconds: int
    current_legs: list[ArbLegResponse] | None = None


class ArbResponse(BaseModel):
    id: int
    match: str
    sport: str
    league: str
    commence_time: str
    market_type: str
    profit_pct: float
    total_implied: float
    legs: list[ArbLegResponse]
    status: ArbStatus
    detected_at: str


class ArbHistoryItem(BaseModel):
    id: int
    match: str
    sport: str
    league: str
    commence_time: str
    market_type: str
    profit_pct: float
    total_implied: float
    num_legs: int
    status: ArbStatus
    detected_at: str
    closed_at: str | None


@router.get("/", response_model=list[ArbResponse])
async def list_arbitrage(
    status: str = "active",
    min_profit: float = 0.0,
    db: AsyncSession = Depends(get_db),
):
    """Lista oportunidades de arbitraje."""
    query = (
        select(ArbitrageOpportunity)
        .where(ArbitrageOpportunity.status == status)
    )
    if min_profit > 0:
        query = query.where(ArbitrageOpportunity.profit_pct >= min_profit)

    query = query.order_by(ArbitrageOpportunity.profit_pct.desc())

    from app.models.sport import League, Season, Sport

    result = (await db.execute(query)).scalars().all()

    response = []
    for arb in result:
        match = await db.get(Match, arb.match_id)
        market = await db.get(Market, arb.market_id)
        market_type = await db.get(MarketType, market.market_type_id)
        home = await db.get(Team, match.home_team_id)
        away = await db.get(Team, match.away_team_id)
        season = await db.get(Season, match.season_id)
        league = await db.get(League, season.league_id)
        sport = await db.get(Sport, league.sport_id)

        response.append(ArbResponse(
            id=arb.id,
            match=f"{home.canonical_name} vs {away.canonical_name}",
            sport=sport.key,
            league=league.key,
            commence_time=match.commence_time.strftime("%Y-%m-%d %H:%M UTC"),
            market_type=market_type.key,
            profit_pct=float(arb.profit_pct),
            total_implied=float(arb.total_implied),
            legs=arb.legs,
            status=arb.status,
            detected_at=arb.detected_at.strftime("%Y-%m-%d %H:%M UTC"),
        ))

    return response


@router.get("/history", response_model=list[ArbHistoryItem])
async def arbitrage_history(
    status: str | None = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
):
    """
    Historial completo de arbitrajes (todos los estados por defecto).
    Incluye `closed_at` y `sport` para visualización.
    """
    from app.models.sport import League, Season, Sport

    limit = max(1, min(limit, 500))

    query = (
        select(ArbitrageOpportunity)
        .order_by(ArbitrageOpportunity.detected_at.desc())
        .limit(limit)
    )
    if status:
        query = query.where(ArbitrageOpportunity.status == status)

    result = (await db.execute(query)).scalars().all()

    response = []
    for arb in result:
        match = await db.get(Match, arb.match_id)
        market = await db.get(Market, arb.market_id)
        market_type = await db.get(MarketType, market.market_type_id)
        home = await db.get(Team, match.home_team_id)
        away = await db.get(Team, match.away_team_id)
        season = await db.get(Season, match.season_id)
        league = await db.get(League, season.league_id)
        sport = await db.get(Sport, league.sport_id)

        response.append(ArbHistoryItem(
            id=arb.id,
            match=f"{home.canonical_name} vs {away.canonical_name}",
            sport=sport.key,
            league=league.key,
            commence_time=match.commence_time.strftime("%Y-%m-%d %H:%M UTC"),
            market_type=market_type.key,
            profit_pct=float(arb.profit_pct),
            total_implied=float(arb.total_implied),
            num_legs=len(arb.legs) if arb.legs else 0,
            status=arb.status,
            detected_at=arb.detected_at.strftime("%Y-%m-%d %H:%M UTC"),
            closed_at=arb.closed_at.strftime("%Y-%m-%d %H:%M UTC") if arb.closed_at else None,
        ))

    return response


@router.get("/{arb_id}/revalidate", response_model=RevalidationResponse)
async def revalidate_arbitrage(arb_id: int, db: AsyncSession = Depends(get_db)):
    """
    Re-evalúa el arb contra las cuotas más recientes en DB. Devuelve si sigue
    siendo ejecutable (alive), requiere confirmación por haber caído de valor
    (stale), o ya no existe (dead). No modifica estado.
    """
    # Mismos parámetros que el detector — la revalidación NO debe ser más
    # permisiva que la detección (en particular, max_odds_age_minutes).
    svc = ArbitrageDetectionService(
        min_profit_pct=settings.ARB_MIN_PROFIT_PCT,
        min_bookmakers=settings.ARB_MIN_BOOKMAKERS,
        max_odds_age_minutes=settings.ARB_MAX_ODDS_AGE_MINUTES,
        max_minutes_to_kickoff=settings.ARB_MAX_HOURS_TO_KICKOFF * 60,
    )
    try:
        result = await svc.revalidate_arb(db, arb_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return RevalidationResponse(
        status=result.status,
        detected_profit_pct=result.detected_profit_pct,
        current_profit_pct=result.current_profit_pct,
        age_seconds=result.age_seconds,
        current_legs=result.current_legs,
    )
