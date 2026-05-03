from datetime import datetime

from pydantic import BaseModel


class OpportunityResponse(BaseModel):
    id: int
    match_home_team: str
    match_away_team: str
    commence_time: datetime
    market_type: str
    outcome_name: str
    bookmaker_name: str
    odds_price: float
    consensus_prob: float
    implied_prob: float
    value_pct: float
    kelly_stake_pct: float | None
    is_steam: bool = False
    status: str
    detected_at: datetime

    model_config = {"from_attributes": True}


class OpportunityDetailResponse(OpportunityResponse):
    recommended_stake: float | None = None
    staking_method: str | None = None
    bankroll_used: float | None = None


class TakeOpportunityRequest(BaseModel):
    bankroll_id: int
    staking_method: str | None = None


class TakeOpportunityResponse(BaseModel):
    bet_id: int
    stake_amount: float
    odds_at_placement: float
    staking_method: str

    model_config = {"from_attributes": True}
