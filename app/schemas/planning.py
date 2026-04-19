"""Schemas para el planificador diario."""

from pydantic import BaseModel


class AllocationSuggestionResponse(BaseModel):
    arbitrage_id: int
    match_label: str
    market_type: str
    profit_pct: float
    suggested_stake: float
    expected_profit: float
    bookmakers: list[str]


class DailyPlanResponse(BaseModel):
    currency: str
    daily_investment_cap: float
    target_pct: float
    target_profit: float
    max_stake_per_arb_pct: float
    available_arbs: int
    allocations: list[AllocationSuggestionResponse]
    total_suggested_stake: float
    expected_total_profit: float
    target_coverage_pct: float
    # empty | unachievable | achievable | exceeded
    status: str
    recommendation: str
    # Exposición total por bookmaker a través de todos los legs del plan.
    # Permite al usuario ver si un libro queda con mucho capital concentrado
    # (ej. porque aparece en múltiples arbs) y evitar exceder límites de cuenta.
    exposure_by_bookmaker: dict[str, float] = {}
    # Warnings textuales: lista de libros con > 30% del cap asignado.
    concentration_warnings: list[str] = []
