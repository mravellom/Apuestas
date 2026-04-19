"""Schemas para ejecución de apuestas reales."""

from datetime import datetime

from pydantic import BaseModel, Field


class ExecuteArbitrageRequest(BaseModel):
    bankroll_id: int
    total_stake: float = Field(gt=0)
    force_if_stale: bool = False


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


class OutcomeScenarioResponse(BaseModel):
    outcome_key: str
    outcome_name: str
    pnl: float
    covered: bool


class LegSummaryResponse(BaseModel):
    bet_id: int
    outcome_key: str
    outcome_name: str
    bookmaker_key: str
    bookmaker_name: str
    stake_amount: float
    status: str
    odds_effective: float | None
    commission_pct: float


class ReplacementOptionResponse(BaseModel):
    bookmaker_key: str
    bookmaker_name: str
    odds: float
    commission_pct: float


class ReplacementSuggestionResponse(BaseModel):
    outcome_key: str
    outcome_name: str
    rejected_bookmaker_key: str
    alternatives: list[ReplacementOptionResponse]


class ExposureResponse(BaseModel):
    arbitrage_id: int
    currency: str
    is_partial_fill: bool
    any_rejected: bool
    all_placed: bool
    total_placed_stake: float
    worst_case_pnl: float
    best_case_pnl: float
    scenarios: list[OutcomeScenarioResponse]
    legs: list[LegSummaryResponse]
    replacement_suggestions: list[ReplacementSuggestionResponse]


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
