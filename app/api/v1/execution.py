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
    LegInstructionResponse,
    PlaceBetRequest,
    RejectBetRequest,
    SettleBetRequest,
)
from app.services.execution_service import ExecutionError, ExecutionService

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
