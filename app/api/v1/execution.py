"""
Endpoints de ejecución manual de arbitrajes y gestión del ciclo de vida de apuestas.

El flujo:
  1. POST /arbitrage/{id}/execute — crea N bets en pending, reserva bankroll
  2. PATCH /bets/{id}/place — usuario marca colocada con cuota real
  3. PATCH /bets/{id}/reject — libera reserve
  4. PATCH /bets/{id}/settle — liquida con resultado real
"""

from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.models.opportunity import BetTracking
from app.schemas.execution import (
    BetResponse,
    ExecuteArbitrageRequest,
    ExecutionPlanResponse,
    ExposureResponse,
    LegInstructionResponse,
    LegSummaryResponse,
    OutcomeScenarioResponse,
    PlaceBetRequest,
    RejectBetRequest,
    ReplacementOptionResponse,
    ReplacementSuggestionResponse,
    SettleBetRequest,
)
from app.services.execution_service import (
    DeadArbError,
    ExecutionError,
    ExecutionService,
    StaleArbError,
)

router = APIRouter(tags=["execution"])


@router.post(
    "/arbitrage/{arbitrage_id}/execute",
    response_model=ExecutionPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
async def execute_arbitrage(
    arbitrage_id: int,
    payload: ExecuteArbitrageRequest,
    db: DB,
    user: CurrentUser,
):
    svc = ExecutionService()
    try:
        plan = await svc.execute_arbitrage_manual(
            db,
            arbitrage_id=arbitrage_id,
            user_id=user.id,
            bankroll_id=payload.bankroll_id,
            total_stake=Decimal(str(payload.total_stake)),
            force_if_stale=payload.force_if_stale,
        )
    except StaleArbError as e:
        # 409 Conflict con info de revalidación — el cliente decide si reintentar
        # con force_if_stale=True tras mostrar el detalle al usuario.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "stale_arb",
                "message": str(e),
                "revalidation": {
                    "status": e.revalidation.status,
                    "detected_profit_pct": e.revalidation.detected_profit_pct,
                    "current_profit_pct": e.revalidation.current_profit_pct,
                    "age_seconds": e.revalidation.age_seconds,
                },
            },
        )
    except DeadArbError as e:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error": "dead_arb",
                "message": str(e),
                "revalidation": {
                    "status": e.revalidation.status,
                    "detected_profit_pct": e.revalidation.detected_profit_pct,
                    "current_profit_pct": e.revalidation.current_profit_pct,
                    "age_seconds": e.revalidation.age_seconds,
                },
            },
        )
    except ExecutionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return ExecutionPlanResponse(
        arbitrage_id=plan.arbitrage_id,
        match_label=plan.match_label,
        market_type=plan.market_type,
        total_stake=float(plan.total_stake),
        currency=plan.currency,
        expected_profit=float(plan.expected_profit),
        profit_pct=float(plan.profit_pct),
        legs=[
            LegInstructionResponse(
                bet_id=leg.bet_id,
                bookmaker_key=leg.bookmaker_key,
                bookmaker_name=leg.bookmaker_name,
                outcome_key=leg.outcome_key,
                outcome_name=leg.outcome_name,
                stake_amount=float(leg.stake_amount),
                target_odds=float(leg.target_odds),
                min_acceptable_odds=float(leg.min_acceptable_odds),
                commission_pct=float(leg.commission_pct),
            )
            for leg in plan.legs
        ],
    )


@router.get("/arbitrage/{arbitrage_id}/exposure", response_model=ExposureResponse)
async def get_arbitrage_exposure(
    arbitrage_id: int,
    db: DB,
    user: CurrentUser,
):
    """
    Exposición actual del usuario sobre este arb: P&L por escenario de outcome,
    detección de partial fill, sugerencias de rebalanceo por leg rejected.
    """
    svc = ExecutionService()
    try:
        exp = await svc.compute_exposure(
            db, arbitrage_id=arbitrage_id, user_id=user.id
        )
    except ExecutionError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return ExposureResponse(
        arbitrage_id=exp.arbitrage_id,
        currency=exp.currency,
        is_partial_fill=exp.is_partial_fill,
        any_rejected=exp.any_rejected,
        all_placed=exp.all_placed,
        total_placed_stake=float(exp.total_placed_stake),
        worst_case_pnl=float(exp.worst_case_pnl),
        best_case_pnl=float(exp.best_case_pnl),
        scenarios=[
            OutcomeScenarioResponse(
                outcome_key=s.outcome_key,
                outcome_name=s.outcome_name,
                pnl=float(s.pnl),
                covered=s.covered,
            )
            for s in exp.scenarios
        ],
        legs=[
            LegSummaryResponse(
                bet_id=l.bet_id,
                outcome_key=l.outcome_key,
                outcome_name=l.outcome_name,
                bookmaker_key=l.bookmaker_key,
                bookmaker_name=l.bookmaker_name,
                stake_amount=float(l.stake_amount),
                status=l.status,
                odds_effective=float(l.odds_effective) if l.odds_effective is not None else None,
                commission_pct=float(l.commission_pct),
            )
            for l in exp.legs
        ],
        replacement_suggestions=[
            ReplacementSuggestionResponse(
                outcome_key=r.outcome_key,
                outcome_name=r.outcome_name,
                rejected_bookmaker_key=r.rejected_bookmaker_key,
                alternatives=[
                    ReplacementOptionResponse(
                        bookmaker_key=a.bookmaker_key,
                        bookmaker_name=a.bookmaker_name,
                        odds=float(a.odds),
                        commission_pct=float(a.commission_pct),
                    )
                    for a in r.alternatives
                ],
            )
            for r in exp.replacement_suggestions
        ],
    )


@router.get("/bets", response_model=list[BetResponse])
async def list_bets(
    db: DB,
    user: CurrentUser,
    status_filter: str | None = None,
    arbitrage_id: int | None = None,
    limit: int = 50,
):
    query = select(BetTracking).where(BetTracking.user_id == user.id)
    if status_filter:
        query = query.where(BetTracking.status == status_filter)
    if arbitrage_id is not None:
        query = query.where(BetTracking.arbitrage_id == arbitrage_id)
    query = query.order_by(BetTracking.created_at.desc()).limit(limit)

    rows = (await db.execute(query)).scalars().all()
    return rows


@router.patch("/bets/{bet_id}/place", response_model=BetResponse)
async def place_bet(
    bet_id: int,
    payload: PlaceBetRequest,
    db: DB,
    user: CurrentUser,
):
    svc = ExecutionService()
    try:
        bet = await svc.mark_leg_placed(
            db,
            bet_id=bet_id,
            user_id=user.id,
            odds_at_placement=Decimal(str(payload.odds_at_placement)),
        )
    except ExecutionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return bet


@router.patch("/bets/{bet_id}/reject", response_model=BetResponse)
async def reject_bet(
    bet_id: int,
    payload: RejectBetRequest,
    db: DB,
    user: CurrentUser,
):
    svc = ExecutionService()
    try:
        bet = await svc.mark_leg_rejected(
            db, bet_id=bet_id, user_id=user.id, reason=payload.reason
        )
    except ExecutionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return bet


@router.patch("/bets/{bet_id}/settle", response_model=BetResponse)
async def settle_bet(
    bet_id: int,
    payload: SettleBetRequest,
    db: DB,
    user: CurrentUser,
):
    svc = ExecutionService()
    try:
        bet = await svc.settle_leg(
            db,
            bet_id=bet_id,
            user_id=user.id,
            result=payload.result,
            actual_payout=Decimal(str(payload.actual_payout)),
        )
    except ExecutionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return bet
