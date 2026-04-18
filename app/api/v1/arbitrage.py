"""Endpoints de arbitraje."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.arbitrage import ArbitrageOpportunity
from app.models.match import Match
from app.models.market import Market, MarketType
from app.models.team import Team

router = APIRouter(prefix="/arbitrage", tags=["arbitrage"])


class ArbResponse(BaseModel):
    id: int
    match: str
    commence_time: str
    market_type: str
    profit_pct: float
    total_implied: float
    legs: list[dict]
    status: str
    detected_at: str


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

    result = (await db.execute(query)).scalars().all()

    response = []
    for arb in result:
        match = await db.get(Match, arb.match_id)
        market = await db.get(Market, arb.market_id)
        market_type = await db.get(MarketType, market.market_type_id)
        home = await db.get(Team, match.home_team_id)
        away = await db.get(Team, match.away_team_id)

        response.append(ArbResponse(
            id=arb.id,
            match=f"{home.canonical_name} vs {away.canonical_name}",
            commence_time=match.commence_time.strftime("%Y-%m-%d %H:%M UTC"),
            market_type=market_type.key,
            profit_pct=float(arb.profit_pct),
            total_implied=float(arb.total_implied),
            legs=arb.legs,
            status=arb.status,
            detected_at=arb.detected_at.strftime("%Y-%m-%d %H:%M UTC"),
        ))

    return response
