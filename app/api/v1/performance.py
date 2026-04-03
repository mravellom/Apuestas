from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.formulas import calculate_roi
from app.models.opportunity import BetTracking
from app.schemas.user import PerformanceSummary

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("/summary", response_model=PerformanceSummary)
async def get_summary(db: DB, user: CurrentUser):
    result = await db.execute(
        select(BetTracking).where(BetTracking.user_id == user.id)
    )
    bets = result.scalars().all()

    total_bets = len(bets)
    won = sum(1 for b in bets if b.result == "won")
    lost = sum(1 for b in bets if b.result == "lost")
    pending = sum(1 for b in bets if b.result is None)
    total_staked = float(sum(b.stake_amount for b in bets))
    total_profit = float(sum(b.profit_loss or 0 for b in bets))
    win_rate = (won / (won + lost) * 100) if (won + lost) > 0 else 0.0
    roi = calculate_roi(total_profit, total_staked)

    return PerformanceSummary(
        total_bets=total_bets,
        won=won,
        lost=lost,
        pending=pending,
        win_rate=round(win_rate, 2),
        total_staked=round(total_staked, 2),
        total_profit=round(total_profit, 2),
        roi=round(roi, 2),
    )
