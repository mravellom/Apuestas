"""Endpoints de paper trading: listado de apuestas simuladas y métricas."""

import math
import statistics
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.bookmaker import Bookmaker
from app.models.market import Outcome
from app.models.match import Match
from app.models.paper import PaperBet
from app.models.team import Team

router = APIRouter(prefix="/paper", tags=["paper"])


PaperSource = Literal["value", "arbitrage"]
PaperResult = Literal["pending", "won", "lost", "void"]


class PaperBetResponse(BaseModel):
    id: int
    source_type: PaperSource
    match: str
    outcome: str
    bookmaker: str
    odds_taken: float
    stake_units: float
    ev_at_placement: float | None
    placed_at: str
    result: PaperResult
    profit_units: float | None


class StatsBreakdown(BaseModel):
    """Agregado por bucket (source o bookmaker) en `/paper/stats`."""
    bets: int
    profit_units: float


class StatsResponse(BaseModel):
    total_bets: int
    pending: int
    won: int
    lost: int
    void: int
    total_staked_units: float
    total_profit_units: float
    roi_pct: float | None
    win_rate_pct: float | None
    by_source: dict[str, StatsBreakdown]
    by_bookmaker: dict[str, StatsBreakdown]


def _as_float(d: Decimal | None) -> float | None:
    return None if d is None else float(d)


@router.get("/bets", response_model=list[PaperBetResponse])
async def list_paper_bets(
    result: str | None = None,
    source_type: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    query = select(PaperBet).order_by(PaperBet.placed_at.desc()).limit(limit)
    if result:
        query = query.where(PaperBet.result == result)
    if source_type:
        query = query.where(PaperBet.source_type == source_type)

    bets = (await db.execute(query)).scalars().all()

    response = []
    for b in bets:
        match = await db.get(Match, b.match_id)
        outcome = await db.get(Outcome, b.outcome_id)
        bookmaker = await db.get(Bookmaker, b.bookmaker_id)
        home = await db.get(Team, match.home_team_id) if match else None
        away = await db.get(Team, match.away_team_id) if match else None
        response.append(
            PaperBetResponse(
                id=b.id,
                source_type=b.source_type,
                match=f"{home.canonical_name} vs {away.canonical_name}" if home and away else "?",
                outcome=outcome.name if outcome else "?",
                bookmaker=bookmaker.key if bookmaker else "?",
                odds_taken=float(b.odds_taken),
                stake_units=float(b.stake_units),
                ev_at_placement=_as_float(b.ev_at_placement),
                placed_at=b.placed_at.strftime("%Y-%m-%d %H:%M UTC"),
                result=b.result,
                profit_units=_as_float(b.profit_units),
            )
        )
    return response


@router.get("/stats", response_model=StatsResponse)
async def paper_stats(
    source_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Métricas agregadas del paper trading. `source_type` filtra a un origen."""
    source_filter = (PaperBet.source_type == source_type) if source_type else None

    result_query = select(PaperBet.result, func.count()).group_by(PaperBet.result)
    if source_filter is not None:
        result_query = result_query.where(source_filter)
    by_result = dict((r, c) for r, c in (await db.execute(result_query)).all())
    total = sum(by_result.values())
    resolved = by_result.get("won", 0) + by_result.get("lost", 0)

    totals_query = select(
        func.coalesce(func.sum(PaperBet.stake_units), 0),
        func.coalesce(func.sum(PaperBet.profit_units), 0),
    ).where(PaperBet.result.in_(["won", "lost", "void"]))
    if source_filter is not None:
        totals_query = totals_query.where(source_filter)
    totals = (await db.execute(totals_query)).one()
    total_staked = float(totals[0])
    total_profit = float(totals[1])
    roi = (total_profit / total_staked * 100.0) if total_staked > 0 else None
    win_rate = (by_result.get("won", 0) / resolved * 100.0) if resolved > 0 else None

    by_source_query = select(
        PaperBet.source_type,
        func.count(),
        func.coalesce(func.sum(PaperBet.profit_units), 0),
    ).group_by(PaperBet.source_type)
    if source_filter is not None:
        by_source_query = by_source_query.where(source_filter)
    by_source_rows = (await db.execute(by_source_query)).all()
    by_source = {
        row[0]: StatsBreakdown(bets=row[1], profit_units=float(row[2]))
        for row in by_source_rows
    }

    by_bm_query = (
        select(
            Bookmaker.key,
            func.count(),
            func.coalesce(func.sum(PaperBet.profit_units), 0),
        )
        .join(Bookmaker, Bookmaker.id == PaperBet.bookmaker_id)
        .group_by(Bookmaker.key)
    )
    if source_filter is not None:
        by_bm_query = by_bm_query.where(source_filter)
    by_bm_rows = (await db.execute(by_bm_query)).all()
    by_bookmaker = {
        row[0]: StatsBreakdown(bets=row[1], profit_units=float(row[2]))
        for row in by_bm_rows
    }

    return StatsResponse(
        total_bets=total,
        pending=by_result.get("pending", 0),
        won=by_result.get("won", 0),
        lost=by_result.get("lost", 0),
        void=by_result.get("void", 0),
        total_staked_units=total_staked,
        total_profit_units=total_profit,
        roi_pct=roi,
        win_rate_pct=win_rate,
        by_source=by_source,
        by_bookmaker=by_bookmaker,
    )


class EquityPoint(BaseModel):
    """Un punto de la curva de equity (1 por apuesta settled)."""
    timestamp: str
    bet_count: int
    cumulative_profit: float
    drawdown_units: float


class EquityCurveResponse(BaseModel):
    points: list[EquityPoint]
    max_drawdown_units: float
    # Sharpe proxy: media / stdev de returns diarios. Null si <10 settled
    # o <2 días distintos — sin volumen no es señal, es ruido.
    sharpe_proxy: float | None


@router.get("/equity-curve", response_model=EquityCurveResponse)
async def paper_equity_curve(
    source_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Curva de equity acumulada para validar degradación del edge.

    Devuelve un punto por apuesta resuelta (won/lost/void) en orden
    cronológico, con `cumulative_profit` y `drawdown_units` (peak − current).
    Suma `sharpe_proxy` = mean/stdev de returns diarios — informativo, no
    riguroso (no anualizado, no risk-free rate).

    `source_type` filtra a "arbitrage" o "value" para ver cada estrategia
    por separado.
    """
    from collections import defaultdict

    query = (
        select(PaperBet.placed_at, PaperBet.profit_units)
        .where(PaperBet.result.in_(["won", "lost", "void"]))
        .order_by(PaperBet.placed_at.asc())
    )
    if source_type:
        query = query.where(PaperBet.source_type == source_type)
    rows = (await db.execute(query)).all()

    points: list[EquityPoint] = []
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for i, (placed_at, profit) in enumerate(rows):
        cumulative += float(profit or 0)
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)
        points.append(EquityPoint(
            timestamp=placed_at.isoformat() if placed_at else "",
            bet_count=i + 1,
            cumulative_profit=round(cumulative, 4),
            drawdown_units=round(dd, 4),
        ))

    sharpe: float | None = None
    if len(rows) >= 10:
        daily: dict = defaultdict(float)
        for placed_at, profit in rows:
            if placed_at is None:
                continue
            daily[placed_at.date()] += float(profit or 0)
        returns = list(daily.values())
        if len(returns) >= 2:
            stdev_r = statistics.stdev(returns)
            sharpe = (
                round(statistics.mean(returns) / stdev_r, 4) if stdev_r > 0 else 0.0
            )

    return EquityCurveResponse(
        points=points,
        max_drawdown_units=round(max_dd, 4),
        sharpe_proxy=sharpe,
    )


class CLVBreakdown(BaseModel):
    bets: int
    avg_clv_pct: float
    avg_log_clv: float


class CLVResponse(BaseModel):
    total_bets: int
    bets_with_clv: int
    coverage_pct: float
    avg_clv_pct: float | None
    median_clv_pct: float | None
    avg_log_clv: float | None
    positive_count: int
    zero_count: int
    negative_count: int
    by_source: dict[str, CLVBreakdown]
    by_bookmaker: dict[str, CLVBreakdown]


@router.get("/clv", response_model=CLVResponse)
async def paper_clv(
    source_type: str | None = None,
    bookmaker_key: str | None = None,
    result: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Closing Line Value: cuánto batiste a la línea de cierre en promedio.

    CLV positivo = tomaste cuotas mejores que el cierre → señal de skill.
    Mejor predictor del edge real que el ROI a corto plazo (varianza dominante).
    """
    base_filters = []
    if source_type:
        base_filters.append(PaperBet.source_type == source_type)
    if bookmaker_key:
        base_filters.append(Bookmaker.key == bookmaker_key)
    if result:
        base_filters.append(PaperBet.result == result)

    total_query = (
        select(func.count())
        .select_from(PaperBet)
        .join(Bookmaker, Bookmaker.id == PaperBet.bookmaker_id)
    )
    if base_filters:
        total_query = total_query.where(*base_filters)
    total_bets = (await db.execute(total_query)).scalar_one()

    rows_query = (
        select(
            PaperBet.odds_taken,
            PaperBet.closing_odds,
            PaperBet.source_type,
            Bookmaker.key,
        )
        .join(Bookmaker, Bookmaker.id == PaperBet.bookmaker_id)
        .where(PaperBet.closing_odds.is_not(None))
    )
    if base_filters:
        rows_query = rows_query.where(*base_filters)
    rows = (await db.execute(rows_query)).all()

    bets_with_clv = len(rows)
    coverage = (bets_with_clv / total_bets * 100.0) if total_bets > 0 else 0.0

    if bets_with_clv == 0:
        return CLVResponse(
            total_bets=total_bets,
            bets_with_clv=0,
            coverage_pct=0.0,
            avg_clv_pct=None,
            median_clv_pct=None,
            avg_log_clv=None,
            positive_count=0,
            zero_count=0,
            negative_count=0,
            by_source={},
            by_bookmaker={},
        )

    clv_pcts: list[float] = []
    log_clvs: list[float] = []
    pos = neg = zero = 0
    by_source_acc: dict[str, list[tuple[float, float]]] = {}
    by_bm_acc: dict[str, list[tuple[float, float]]] = {}

    for odds_taken, closing_odds, src, bm_key in rows:
        # closing_odds puede salir como Decimal('0') si quedó mal; saltarlo para evitar div/0.
        if closing_odds is None or float(closing_odds) <= 0:
            continue
        ot = float(odds_taken)
        co = float(closing_odds)
        clv = ot / co - 1.0
        log_clv = math.log(ot / co)
        clv_pcts.append(clv)
        log_clvs.append(log_clv)
        if clv > 0:
            pos += 1
        elif clv < 0:
            neg += 1
        else:
            zero += 1
        by_source_acc.setdefault(src, []).append((clv, log_clv))
        by_bm_acc.setdefault(bm_key, []).append((clv, log_clv))

    def _summarize(items: list[tuple[float, float]]) -> CLVBreakdown:
        clvs = [c for c, _ in items]
        logs = [lg for _, lg in items]
        return CLVBreakdown(
            bets=len(items),
            avg_clv_pct=statistics.fmean(clvs),
            avg_log_clv=statistics.fmean(logs),
        )

    return CLVResponse(
        total_bets=total_bets,
        bets_with_clv=bets_with_clv,
        coverage_pct=round(coverage, 2),
        avg_clv_pct=statistics.fmean(clv_pcts),
        median_clv_pct=statistics.median(clv_pcts),
        avg_log_clv=statistics.fmean(log_clvs),
        positive_count=pos,
        zero_count=zero,
        negative_count=neg,
        by_source={k: _summarize(v) for k, v in by_source_acc.items()},
        by_bookmaker={k: _summarize(v) for k, v in by_bm_acc.items()},
    )
