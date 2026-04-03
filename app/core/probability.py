"""Motor de probabilidades: consenso de mercado."""

from dataclasses import dataclass

from app.core.formulas import consensus_probability


@dataclass
class MarketConsensus:
    """Resultado del cálculo de consenso para un mercado."""

    outcome_keys: list[str]
    fair_probabilities: list[float]
    num_bookmakers: int


def calculate_market_consensus(
    odds_by_bookmaker: dict[str, list[float]],
    outcome_keys: list[str],
    sharp_bookmakers: set[str] | None = None,
) -> MarketConsensus:
    """
    Calcula el consenso de probabilidades para un mercado.

    Args:
        odds_by_bookmaker: {bookmaker_key: [odds per outcome]}
        outcome_keys: ["home", "draw", "away"] o similar
        sharp_bookmakers: bookmakers con mayor peso

    Returns:
        MarketConsensus con probabilidades justas por outcome
    """
    fair_probs = consensus_probability(odds_by_bookmaker, sharp_bookmakers)
    return MarketConsensus(
        outcome_keys=outcome_keys,
        fair_probabilities=fair_probs,
        num_bookmakers=len(odds_by_bookmaker),
    )
