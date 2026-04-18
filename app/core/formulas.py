"""
Funciones puras de cálculo para ValueBet Engine.
Todas son stateless y 100% testeables.
"""


def implied_probability(decimal_odds: float) -> float:
    """Convierte cuota decimal a probabilidad implícita."""
    if decimal_odds <= 0:
        raise ValueError("Odds must be positive")
    return 1.0 / decimal_odds


def remove_vig_proportional(implied_probs: list[float]) -> list[float]:
    """
    Remueve el vig (margen de la casa) proporcionalmente.
    Divide cada probabilidad implícita por la suma total (overround).
    """
    total = sum(implied_probs)
    if total <= 0:
        raise ValueError("Sum of probabilities must be positive")
    return [p / total for p in implied_probs]


def remove_vig_shin(implied_probs: list[float], tol: float = 1e-8, max_iter: int = 100) -> list[float]:
    """
    Remueve el vig usando el modelo Shin (1993).
    Corrige el sesgo de longshots: las casas cargan más margen en outsiders.
    Resuelve z (fracción de insiders) via bisección tal que sum(p_i) = 1.
    """
    import math

    overround = sum(implied_probs)
    if overround <= 1.0:
        return remove_vig_proportional(implied_probs)

    def fair_probs_for_z(z: float) -> list[float]:
        denom = 2.0 * (1.0 - z)
        return [
            (math.sqrt(z ** 2 + 4.0 * (1.0 - z) * (q * q / overround)) - z) / denom
            for q in implied_probs
        ]

    lo, hi = 0.0, 0.99
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        s = sum(fair_probs_for_z(mid))
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = mid
        else:
            hi = mid

    return fair_probs_for_z(mid)


def odds_to_fair_probs(odds_list: list[float], method: str = "shin") -> list[float]:
    """Convierte una lista de cuotas a probabilidades justas (sin vig)."""
    implied = [implied_probability(o) for o in odds_list]
    if method == "shin":
        return remove_vig_shin(implied)
    return remove_vig_proportional(implied)


def value_calculation(fair_probability: float, decimal_odds: float) -> float:
    """
    Calcula el expected value de una apuesta.
    Retorna el porcentaje de valor: > 0 indica value bet.
    Formula: (prob_real * cuota) - 1
    """
    return (fair_probability * decimal_odds) - 1.0


def kelly_criterion(probability: float, decimal_odds: float) -> float:
    """
    Kelly Criterion completo.
    Retorna la fracción óptima del bankroll a apostar.
    Formula: f* = (b*p - q) / b, donde b = odds-1, p = prob, q = 1-p
    """
    if decimal_odds <= 1.0:
        return 0.0
    b = decimal_odds - 1.0
    q = 1.0 - probability
    kelly = (b * probability - q) / b
    return max(0.0, kelly)


def fractional_kelly(probability: float, decimal_odds: float, fraction: float = 0.25) -> float:
    """Kelly fraccionado. Default 1/4 Kelly."""
    return kelly_criterion(probability, decimal_odds) * fraction


def flat_stake(bankroll: float, percentage: float = 0.02) -> float:
    """Stake fijo como porcentaje del bankroll."""
    return bankroll * percentage


def consensus_probability(
    odds_by_bookmaker: dict[str, list[float]],
    sharp_bookmakers: set[str] | None = None,
    sharp_weight: float = 2.0,
) -> list[float]:
    """
    Calcula probabilidad consenso para un mercado completo.

    Args:
        odds_by_bookmaker: {bookmaker_key: [odds_outcome_1, odds_outcome_2, ...]}
        sharp_bookmakers: set de keys de bookmakers sharp (ej: {"pinnacle", "betfair"})
        sharp_weight: peso extra para bookmakers sharp (default 2x)

    Returns:
        Lista de probabilidades consenso para cada outcome.
    """
    if not odds_by_bookmaker:
        raise ValueError("No bookmaker odds provided")

    sharp_bookmakers = sharp_bookmakers or set()
    num_outcomes = len(next(iter(odds_by_bookmaker.values())))

    weighted_probs: list[float] = [0.0] * num_outcomes
    total_weight = 0.0

    for bookmaker, odds_list in odds_by_bookmaker.items():
        if len(odds_list) != num_outcomes:
            continue
        fair_probs = odds_to_fair_probs(odds_list)
        weight = sharp_weight if bookmaker in sharp_bookmakers else 1.0
        for i, prob in enumerate(fair_probs):
            weighted_probs[i] += prob * weight
        total_weight += weight

    if total_weight <= 0:
        raise ValueError("No valid bookmaker data")

    return [p / total_weight for p in weighted_probs]


def calculate_roi(total_profit: float, total_staked: float) -> float:
    """Calcula ROI como porcentaje."""
    if total_staked <= 0:
        return 0.0
    return (total_profit / total_staked) * 100.0
