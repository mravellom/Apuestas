"""Endpoints de arbitraje."""

from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models.arbitrage import ArbitrageOpportunity
from app.models.match import Match
from app.models.market import Market, MarketType
from app.models.sport import League, Season, Sport
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
    point: float | None = None


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
    last_revalidate_at: str | None = None
    last_revalidate_status: RevalidationStatus | None = None
    last_revalidate_profit_pct: float | None = None


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
    """Lista oportunidades de arbitraje.

    Loadea las relaciones con `selectinload` en una sola pasada en vez del
    patrón previo de 8 `db.get()` por arb (N+1). Para 100 arbs activos esto
    pasa de ~800 queries a ~6 — el dashboard responde de forma constante
    independientemente del volumen.
    """
    query = (
        select(ArbitrageOpportunity)
        .where(ArbitrageOpportunity.status == status)
        .options(
            selectinload(ArbitrageOpportunity.match).selectinload(Match.home_team),
            selectinload(ArbitrageOpportunity.match).selectinload(Match.away_team),
            selectinload(ArbitrageOpportunity.match)
                .selectinload(Match.season)
                .selectinload(Season.league)
                .selectinload(League.sport),
            selectinload(ArbitrageOpportunity.market).selectinload(Market.market_type),
        )
    )
    if min_profit > 0:
        query = query.where(ArbitrageOpportunity.profit_pct >= min_profit)

    query = query.order_by(ArbitrageOpportunity.profit_pct.desc())

    result = (await db.execute(query)).scalars().all()

    response = []
    for arb in result:
        match = arb.match
        market = arb.market
        market_type = market.market_type
        home = match.home_team
        away = match.away_team
        league = match.season.league
        sport = league.sport

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
            last_revalidate_at=(
                arb.last_revalidate_at.strftime("%Y-%m-%d %H:%M UTC")
                if arb.last_revalidate_at else None
            ),
            last_revalidate_status=arb.last_revalidate_status,
            last_revalidate_profit_pct=(
                float(arb.last_revalidate_profit_pct)
                if arb.last_revalidate_profit_pct is not None else None
            ),
        ))

    return response


@router.get("/history", response_model=list[ArbHistoryItem])
async def arbitrage_history(
    status: str | None = None,
    limit: int = 200,
    from_date: date | None = Query(None, description="Filter detected_at >= from_date (UTC)"),
    to_date: date | None = Query(None, description="Filter detected_at <= to_date end-of-day (UTC)"),
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
    if from_date:
        query = query.where(
            ArbitrageOpportunity.detected_at >= datetime.combine(from_date, datetime.min.time())
        )
    if to_date:
        query = query.where(
            ArbitrageOpportunity.detected_at < datetime.combine(to_date + timedelta(days=1), datetime.min.time())
        )

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


class ArbQualityResponse(BaseModel):
    """
    Métricas agregadas para distinguir señal vs ruido en una ventana de tiempo.

    - total: arbs detectados en la ventana.
    - over_5min: arbs que vivieron >5min (cerraron tras 5min o siguen activos);
      proxy de "ejecutable manualmente". Arbs que mueren en <5min suelen ser
      palp errors corregidos antes de que un humano pueda colocar la apuesta.
    - outliers: arbs con profit_pct >= outlier_threshold (default 10%). El
      histórico muestra que ≥10% es casi siempre palp error.
    - signal_ratio: (total - outliers) / total. 1.0 = sin ruido.
    - paper_settled_units: suma de profit_units de paper_bets de tipo
      arbitrage en la misma ventana (positivo = el detector tiene edge).
    """
    window_days: int
    total: int
    over_5min: int
    outliers: int
    signal_ratio: float
    paper_settled_bets: int
    paper_settled_units: float


@router.get("/quality", response_model=ArbQualityResponse)
async def arbitrage_quality(
    window_days: int = Query(30, ge=1, le=180),
    outlier_threshold_pct: float = Query(10.0, ge=1.0),
    min_lifetime_minutes: int = Query(5, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """
    Métricas de calidad del detector de arbs. Separa volumen (todo lo que
    encontramos) de señal (lo que probablemente era ejecutable).
    """
    from sqlalchemy import func

    cutoff = datetime.utcnow() - timedelta(days=window_days)

    # Vida útil: closed_at - detected_at para cerrados; NOW() - detected_at
    # para los activos (siguen vivos, así que ya >= su edad actual).
    lifetime_minutes = (
        func.extract(
            "epoch",
            func.coalesce(ArbitrageOpportunity.closed_at, func.now())
            - ArbitrageOpportunity.detected_at,
        )
        / 60.0
    )

    row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.count().filter(lifetime_minutes >= min_lifetime_minutes).label("over_5min"),
                func.count().filter(
                    ArbitrageOpportunity.profit_pct >= outlier_threshold_pct
                ).label("outliers"),
            ).where(ArbitrageOpportunity.detected_at >= cutoff)
        )
    ).one()

    from app.models.paper import PaperBet

    paper_row = (
        await db.execute(
            select(
                func.count().label("settled"),
                func.coalesce(func.sum(PaperBet.profit_units), 0).label("units"),
            ).where(
                PaperBet.source_type == "arbitrage",
                PaperBet.placed_at >= cutoff,
                PaperBet.result.in_(("won", "lost")),
            )
        )
    ).one()

    total = int(row.total or 0)
    outliers = int(row.outliers or 0)
    signal_ratio = (total - outliers) / total if total > 0 else 0.0

    return ArbQualityResponse(
        window_days=window_days,
        total=total,
        over_5min=int(row.over_5min or 0),
        outliers=outliers,
        signal_ratio=round(signal_ratio, 4),
        paper_settled_bets=int(paper_row.settled or 0),
        paper_settled_units=float(paper_row.units or 0),
    )


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
        min_profit_pct_alt=settings.ARB_MIN_PROFIT_PCT_ALT,
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
