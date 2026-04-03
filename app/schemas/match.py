from datetime import datetime

from pydantic import BaseModel


class TeamBrief(BaseModel):
    id: int
    canonical_name: str

    model_config = {"from_attributes": True}


class MatchResponse(BaseModel):
    id: int
    external_id: str | None
    commence_time: datetime
    status: str
    home_score: int | None
    away_score: int | None
    home_team: TeamBrief
    away_team: TeamBrief

    model_config = {"from_attributes": True}


class MatchDetailResponse(MatchResponse):
    season_id: int
    markets: list["MarketResponse"] = []


class MarketResponse(BaseModel):
    id: int
    market_type_key: str
    market_type_name: str
    parameter: float | None
    outcomes: list["OutcomeResponse"] = []

    model_config = {"from_attributes": True}


class OutcomeResponse(BaseModel):
    id: int
    key: str
    name: str

    model_config = {"from_attributes": True}


class OddsResponse(BaseModel):
    outcome_id: int
    outcome_key: str
    outcome_name: str
    bookmaker_key: str
    bookmaker_name: str
    price: float
    captured_at: datetime

    model_config = {"from_attributes": True}
