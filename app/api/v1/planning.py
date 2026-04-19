"""Endpoint del planificador diario de arbs."""

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DB, CurrentUser
from app.schemas.planning import AllocationSuggestionResponse, DailyPlanResponse
from app.services.planning_service import PlanningService

router = APIRouter(prefix="/planning", tags=["planning"])


@router.get("/daily", response_model=DailyPlanResponse)
async def get_daily_plan(
    db: DB,
    user: CurrentUser,
    bankroll_id: int = Query(..., description="ID del bankroll a usar"),
    daily_cap: float | None = Query(
        None,
        description="Tope de inversión para hoy. Si no se pasa, usa "
        "bankroll.available_amount como default.",
    ),
    target_pct: float | None = Query(
        None,
        description="Target de profit diario como %. Si no se pasa, usa "
        "user_config.default_daily_target_pct (default 1.0).",
    ),
    max_stake_per_arb_pct: float | None = Query(
        None,
        description="Tope de stake por arb como % del daily_cap. Si no, usa "
        "user_config.default_max_stake_per_arb_pct (default 15.0).",
    ),
):
    """
    Retorna un plan priorizado: qué arbs ejecutar y con qué stake para cubrir
    el target diario sin exceder el cap.
    """
    svc = PlanningService()
    try:
        plan = await svc.plan_daily(
            db,
            user_id=user.id,
            bankroll_id=bankroll_id,
            daily_investment_cap=Decimal(str(daily_cap)) if daily_cap is not None else None,
            target_pct=Decimal(str(target_pct)) if target_pct is not None else None,
            max_stake_per_arb_pct=(
                Decimal(str(max_stake_per_arb_pct))
                if max_stake_per_arb_pct is not None else None
            ),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )

    return DailyPlanResponse(
        currency=plan.currency,
        daily_investment_cap=float(plan.daily_investment_cap),
        target_pct=float(plan.target_pct),
        target_profit=float(plan.target_profit),
        max_stake_per_arb_pct=float(plan.max_stake_per_arb_pct),
        available_arbs=plan.available_arbs,
        allocations=[
            AllocationSuggestionResponse(
                arbitrage_id=a.arbitrage_id,
                match_label=a.match_label,
                market_type=a.market_type,
                profit_pct=float(a.profit_pct),
                suggested_stake=float(a.suggested_stake),
                expected_profit=float(a.expected_profit),
                bookmakers=a.bookmakers,
            )
            for a in plan.allocations
        ],
        total_suggested_stake=float(plan.total_suggested_stake),
        expected_total_profit=float(plan.expected_total_profit),
        target_coverage_pct=float(plan.target_coverage_pct),
        status=plan.status,
        recommendation=plan.recommendation,
    )
