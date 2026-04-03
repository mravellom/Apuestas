from pydantic import BaseModel, Field


class AlertConfigResponse(BaseModel):
    id: int
    channel: str
    destination: str
    min_value_pct: float
    sports_filter: list[str] | None
    leagues_filter: list[str] | None
    active: bool

    model_config = {"from_attributes": True}


class AlertConfigCreate(BaseModel):
    channel: str = Field(pattern="^(email|telegram|webhook)$")
    destination: str = Field(min_length=1, max_length=500)
    min_value_pct: float = Field(default=0.05, ge=0.0, le=1.0)
    sports_filter: list[str] = []
    leagues_filter: list[str] = []


class AlertConfigUpdate(BaseModel):
    destination: str | None = None
    min_value_pct: float | None = Field(None, ge=0.0, le=1.0)
    sports_filter: list[str] | None = None
    leagues_filter: list[str] | None = None
    active: bool | None = None
