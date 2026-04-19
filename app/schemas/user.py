
from pydantic import BaseModel, Field


class UserConfigResponse(BaseModel):
    default_staking: str
    kelly_fraction: float
    flat_stake_pct: float
    min_value_threshold: float
    max_stake_pct: float
    preferred_sports: list[str] | None
    preferred_leagues: list[str] | None
    risk_tolerance: str

    model_config = {"from_attributes": True}


class UserConfigUpdate(BaseModel):
    default_staking: str | None = None
    kelly_fraction: float | None = Field(None, ge=0.01, le=1.0)
    flat_stake_pct: float | None = Field(None, ge=0.1, le=100.0)
    min_value_threshold: float | None = Field(None, ge=0.0, le=1.0)
    max_stake_pct: float | None = Field(None, ge=0.1, le=100.0)
    preferred_sports: list[str] | None = None
    preferred_leagues: list[str] | None = None
    risk_tolerance: str | None = None


class BankrollResponse(BaseModel):
    id: int
    name: str
    currency: str
    initial_amount: float
    current_amount: float
    reserved_amount: float = 0
    available_amount: float = 0

    model_config = {"from_attributes": True}


class BankrollCreate(BaseModel):
    name: str = "Principal"
    currency: str = "EUR"
    initial_amount: float = Field(gt=0)


class BankrollUpdate(BaseModel):
    name: str | None = None
    current_amount: float | None = Field(None, ge=0)


class PerformanceSummary(BaseModel):
    total_bets: int
    won: int
    lost: int
    pending: int
    win_rate: float
    total_staked: float
    total_profit: float
    roi: float
