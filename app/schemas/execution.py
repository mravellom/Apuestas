"""Schemas para ejecución de apuestas reales."""

from datetime import datetime

from pydantic import BaseModel, Field


class ExecuteArbitrageRequest(BaseModel):
    bankroll_id: int
    total_stake: float = Field(gt=0)


class LegInstructionResponse(BaseModel):
    bet_id: int
    bookmaker_key: str
    bookmaker_name: str
    outcome_key: str
    outcome_name: str
    stake_amount: float
    target_odds: float
    min_acceptable_odds: float
    commission_pct: float


class ExecutionPlanResponse(BaseModel):
    arbitrage_id: int
    match_label: str
    market_type: str
    total_stake: float
    currency: str
    expected_profit: float
    profit_pct: float
    legs: list[LegInstructionResponse]


class PlaceBetRequest(BaseModel):
    odds_at_placement: float = Field(gt=1.0)


class RejectBetRequest(BaseModel):
    reason: str = ""


class SettleBetRequest(BaseModel):
    # won | lost | void | half_won | half_lost
    result: str
    actual_payout: float = Field(ge=0)


class BetResponse(BaseModel):
    id: int
    arbitrage_id: int | None
    opportunity_id: int | None
    bookmaker_id: int
    outcome_id: int
    stake_amount: float
    odds_at_detection: float | None
    odds_at_placement: float | None
    commission_pct: float
    status: str
    result: str | None
    actual_payout: float | None
    profit_loss: float | None
    created_at: datetime
    placed_at: datetime | None
    settled_at: datetime | None

    model_config = {"from_attributes": True}
