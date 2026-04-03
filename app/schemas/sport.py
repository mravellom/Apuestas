from datetime import date

from pydantic import BaseModel


class SportResponse(BaseModel):
    id: int
    key: str
    name: str
    active: bool

    model_config = {"from_attributes": True}


class LeagueResponse(BaseModel):
    id: int
    sport_id: int
    key: str
    name: str
    country: str | None
    active: bool

    model_config = {"from_attributes": True}


class SeasonResponse(BaseModel):
    id: int
    league_id: int
    name: str
    start_date: date | None
    end_date: date | None
    active: bool

    model_config = {"from_attributes": True}
