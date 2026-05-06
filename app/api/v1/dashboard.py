"""Endpoint consolidado para el dashboard."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.api_usage import ApiUsageLog
from app.models.arbitrage import ArbitrageOpportunity
from app.models.bookmaker import Bookmaker
from app.models.market import Market, Outcome
from app.models.match import Match
from app.models.opportunity import Opportunity
from app.models.sport import League, Season, Sport

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class SportActivity(BaseModel):
    sport_key: str
    sport_name: str
    leagues_total: int
    leagues_detection_on: int
    arbs: int
    valuebets: int


class LeagueArbCount(BaseModel):
    league_key: str
    league_name: str
    sport_key: str
    arbs: int
    avg_profit_pct: float
    max_profit_pct: float


class BookCount(BaseModel):
    bookmaker: str
    count: int
    avg_pct: float
    max_pct: float


class ApiUsageSummary(BaseModel):
    source: str
    requests_remaining: int | None
    requests_used: int | None
    last_captured_at: str | None
    calls_24h: int
    calls_7d: int


class HourBucket(BaseModel):
    """Conteo agregado por hora del día (0-23) en horario chileno (America/Santiago)."""
    hour: int  # 0..23
    count: int


class DashboardSummary(BaseModel):
    window_days: int
    generated_at: str
    sports: list[SportActivity]
    top_leagues_by_arbs: list[LeagueArbCount]
    top_books_arbs: list[BookCount]
    top_books_valuebets: list[BookCount]
    api_usage: list[ApiUsageSummary]
    arbs_by_hour_clt: list[HourBucket]
    valuebets_by_hour_clt: list[HourBucket]


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    window_days: int = Query(7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """
    Devuelve todas las métricas del dashboard en una sola respuesta.

    `window_days` controla la ventana para los rankings de arbs/valuebets
    (no afecta a la lista de sports activos, que es estado actual).
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(days=window_days)

    # 1) Sports + leagues activas + counts dentro de la ventana
    sports_meta = (
        await db.execute(
            select(
                Sport.key,
                Sport.name,
                func.count(League.id).label("leagues_total"),
                func.coalesce(
                    func.sum(case((League.detection_enabled.is_(True), 1), else_=0)),
                    0,
                ).label("leagues_on"),
            )
            .join(League, League.sport_id == Sport.id, isouter=True)
            .group_by(Sport.key, Sport.name)
            .order_by(Sport.key)
        )
    ).all()

    # Arbs por sport en la ventana
    arbs_by_sport_rows = (
        await db.execute(
            select(Sport.key, func.count(ArbitrageOpportunity.id))
            .join(Match, Match.id == ArbitrageOpportunity.match_id)
            .join(Season, Season.id == Match.season_id)
            .join(League, League.id == Season.league_id)
            .join(Sport, Sport.id == League.sport_id)
            .where(ArbitrageOpportunity.detected_at >= cutoff)
            .group_by(Sport.key)
        )
    ).all()
    arbs_per_sport = {sk: n for sk, n in arbs_by_sport_rows}

    # Valuebets por sport en la ventana
    vb_by_sport_rows = (
        await db.execute(
            select(Sport.key, func.count(Opportunity.id))
            .join(Outcome, Outcome.id == Opportunity.outcome_id)
            .join(Market, Market.id == Outcome.market_id)
            .join(Match, Match.id == Market.match_id)
            .join(Season, Season.id == Match.season_id)
            .join(League, League.id == Season.league_id)
            .join(Sport, Sport.id == League.sport_id)
            .where(Opportunity.detected_at >= cutoff)
            .group_by(Sport.key)
        )
    ).all()
    vb_per_sport = {sk: n for sk, n in vb_by_sport_rows}

    sports = [
        SportActivity(
            sport_key=row[0],
            sport_name=row[1],
            leagues_total=int(row[2] or 0),
            leagues_detection_on=int(row[3] or 0),
            arbs=arbs_per_sport.get(row[0], 0),
            valuebets=vb_per_sport.get(row[0], 0),
        )
        for row in sports_meta
    ]

    # 2) Top ligas por arbs
    leagues_rows = (
        await db.execute(
            select(
                League.key,
                League.name,
                Sport.key,
                func.count(ArbitrageOpportunity.id).label("arbs"),
                func.avg(ArbitrageOpportunity.profit_pct).label("avg_profit"),
                func.max(ArbitrageOpportunity.profit_pct).label("max_profit"),
            )
            .join(Season, Season.league_id == League.id)
            .join(Match, Match.season_id == Season.id)
            .join(ArbitrageOpportunity, ArbitrageOpportunity.match_id == Match.id)
            .join(Sport, Sport.id == League.sport_id)
            .where(ArbitrageOpportunity.detected_at >= cutoff)
            .group_by(League.key, League.name, Sport.key)
            .order_by(func.count(ArbitrageOpportunity.id).desc())
            .limit(10)
        )
    ).all()
    top_leagues = [
        LeagueArbCount(
            league_key=r[0],
            league_name=r[1],
            sport_key=r[2],
            arbs=int(r[3]),
            avg_profit_pct=float(r[4] or 0),
            max_profit_pct=float(r[5] or 0),
        )
        for r in leagues_rows
    ]

    # 3) Top books por arbs (parsing JSON legs)
    arbs_in_window = (
        await db.execute(
            select(ArbitrageOpportunity.profit_pct, ArbitrageOpportunity.legs)
            .where(ArbitrageOpportunity.detected_at >= cutoff)
        )
    ).all()
    book_arb_stats: dict[str, list[float]] = {}
    for profit_pct, legs in arbs_in_window:
        if not legs:
            continue
        for leg in legs:
            book = leg.get("bookmaker")
            if not book:
                continue
            book_arb_stats.setdefault(book, []).append(float(profit_pct))
    top_books_arbs = sorted(
        [
            BookCount(
                bookmaker=book,
                count=len(profits),
                avg_pct=sum(profits) / len(profits),
                max_pct=max(profits),
            )
            for book, profits in book_arb_stats.items()
        ],
        key=lambda b: b.count,
        reverse=True,
    )[:10]

    # 4) Top books por valuebets
    vb_books_rows = (
        await db.execute(
            select(
                Bookmaker.key,
                func.count(Opportunity.id),
                func.avg(Opportunity.value_pct),
                func.max(Opportunity.value_pct),
            )
            .join(Bookmaker, Bookmaker.id == Opportunity.bookmaker_id)
            .where(Opportunity.detected_at >= cutoff)
            .group_by(Bookmaker.key)
            .order_by(func.count(Opportunity.id).desc())
            .limit(10)
        )
    ).all()
    top_books_vb = [
        BookCount(
            bookmaker=r[0],
            count=int(r[1]),
            avg_pct=float(r[2] or 0),
            max_pct=float(r[3] or 0),
        )
        for r in vb_books_rows
    ]

    # 5) Consumo de la API
    api_sources = (
        await db.execute(select(ApiUsageLog.source).distinct())
    ).scalars().all()
    api_usage_list: list[ApiUsageSummary] = []
    for source in api_sources:
        last = (
            await db.execute(
                select(ApiUsageLog)
                .where(ApiUsageLog.source == source)
                .order_by(ApiUsageLog.captured_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        cutoff_24h = now - timedelta(hours=24)
        cutoff_7d = now - timedelta(days=7)
        calls_24h = (
            await db.execute(
                select(func.count(ApiUsageLog.id))
                .where(ApiUsageLog.source == source, ApiUsageLog.captured_at >= cutoff_24h)
            )
        ).scalar_one()
        calls_7d = (
            await db.execute(
                select(func.count(ApiUsageLog.id))
                .where(ApiUsageLog.source == source, ApiUsageLog.captured_at >= cutoff_7d)
            )
        ).scalar_one()
        api_usage_list.append(
            ApiUsageSummary(
                source=source,
                requests_remaining=last.requests_remaining if last else None,
                requests_used=last.requests_used if last else None,
                last_captured_at=last.captured_at.strftime("%Y-%m-%d %H:%M UTC") if last else None,
                calls_24h=int(calls_24h),
                calls_7d=int(calls_7d),
            )
        )

    # 6) Distribución horaria en horario chileno (America/Santiago).
    # Agregado en Python (no en SQL) para portabilidad: SQLite no tiene
    # `timezone()` y los volúmenes actuales (cientos de filas/ventana) no
    # justifican un path Postgres-only. zoneinfo respeta DST automáticamente
    # — CLT pasa entre UTC-4 y UTC-3 según la fecha.
    from zoneinfo import ZoneInfo
    chile_tz = ZoneInfo("America/Santiago")
    utc_tz = timezone.utc

    def _bucketize(rows: list[datetime]) -> list[HourBucket]:
        counts = [0] * 24
        for dt in rows:
            # detected_at es TIMESTAMP WITHOUT TZ pero guardado como UTC naive
            chile_dt = dt.replace(tzinfo=utc_tz).astimezone(chile_tz)
            counts[chile_dt.hour] += 1
        return [HourBucket(hour=h, count=c) for h, c in enumerate(counts)]

    arb_dts = (
        await db.execute(
            select(ArbitrageOpportunity.detected_at)
            .where(ArbitrageOpportunity.detected_at >= cutoff)
        )
    ).scalars().all()
    arbs_by_hour_clt = _bucketize(arb_dts)

    vb_dts = (
        await db.execute(
            select(Opportunity.detected_at)
            .where(Opportunity.detected_at >= cutoff)
        )
    ).scalars().all()
    valuebets_by_hour_clt = _bucketize(vb_dts)

    return DashboardSummary(
        window_days=window_days,
        generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
        sports=sports,
        top_leagues_by_arbs=top_leagues,
        top_books_arbs=top_books_arbs,
        top_books_valuebets=top_books_vb,
        api_usage=api_usage_list,
        arbs_by_hour_clt=arbs_by_hour_clt,
        valuebets_by_hour_clt=valuebets_by_hour_clt,
    )
