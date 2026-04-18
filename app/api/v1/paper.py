"""Endpoints de paper trading: listado de apuestas simuladas y métricas."""

from decimal import Decimal

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


class PaperBetResponse(BaseModel):
    id: int
    source_type: str
    match: str
    outcome: str
    bookmaker: str
    odds_taken: float
    stake_units: float
    ev_at_placement: float | None
    placed_at: str
    result: str
    profit_units: float | None


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
    by_source: dict
    by_bookmaker: dict


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
async def paper_stats(db: AsyncSession = Depends(get_db)):
    """Métricas agregadas del paper trading."""
    by_result = dict(
        (r, c)
        for r, c in (
            await db.execute(select(PaperBet.result, func.count()).group_by(PaperBet.result))
        ).all()
    )
    total = sum(by_result.values())
    resolved = by_result.get("won", 0) + by_result.get("lost", 0)

    totals = (
        await db.execute(
            select(
                func.coalesce(func.sum(PaperBet.stake_units), 0),
                func.coalesce(func.sum(PaperBet.profit_units), 0),
            ).where(PaperBet.result.in_(["won", "lost", "void"]))
        )
    ).one()
    total_staked = float(totals[0])
    total_profit = float(totals[1])
    roi = (total_profit / total_staked * 100.0) if total_staked > 0 else None
    win_rate = (by_result.get("won", 0) / resolved * 100.0) if resolved > 0 else None

    by_source_rows = (
        await db.execute(
            select(
                PaperBet.source_type,
                func.count(),
                func.coalesce(func.sum(PaperBet.profit_units), 0),
            ).group_by(PaperBet.source_type)
        )
    ).all()
    by_source = {row[0]: {"bets": row[1], "profit_units": float(row[2])} for row in by_source_rows}

    by_bm_rows = (
        await db.execute(
            select(
                Bookmaker.key,
                func.count(),
                func.coalesce(func.sum(PaperBet.profit_units), 0),
            )
            .join(Bookmaker, Bookmaker.id == PaperBet.bookmaker_id)
            .group_by(Bookmaker.key)
        )
    ).all()
    by_bookmaker = {row[0]: {"bets": row[1], "profit_units": float(row[2])} for row in by_bm_rows}

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
