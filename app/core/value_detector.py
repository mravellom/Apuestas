"""Detector de value bets."""

from dataclasses import dataclass

from app.core.formulas import (
    consensus_probability,
    implied_probability,
    kelly_criterion,
    value_calculation,
)


@dataclass
class ValueBet:
    outcome_index: int
    outcome_key: str
    bookmaker_key: str
    bookmaker_odds: float
    consensus_prob: float
    implied_prob: float
    value_pct: float
    kelly_full: float
    edge_confidence: str


def detect_value_bets(
    odds_by_bookmaker: dict[str, list[float]],
    outcome_keys: list[str],
    sharp_bookmakers: set[str] | None = None,
    min_value: float = 0.03,
    min_bookmakers: int = 3,
) -> list[ValueBet]:
    """
    Detecta value bets en un mercado.

    Para cada outcome, calcula la probabilidad consenso y la compara
    con la cuota de cada bookmaker individual. Si el value supera
    min_value, se registra como ValueBet.

    Args:
        odds_by_bookmaker: {bookmaker_key: [odds per outcome]}
        outcome_keys: ["home", "draw", "away"]
        sharp_bookmakers: bookmakers con mayor peso en consenso
        min_value: porcentaje mínimo de value para considerar (default 3%)
        min_bookmakers: mínimo de bookmakers para consenso confiable

    Returns:
        Lista de ValueBet ordenada por value_pct descendente
    """
    if len(odds_by_bookmaker) < min_bookmakers:
        return []

    fair_probs = consensus_probability(odds_by_bookmaker, sharp_bookmakers)
    num_bookmakers = len(odds_by_bookmaker)

    if num_bookmakers >= 6:
        confidence = "high"
    elif num_bookmakers >= 4:
        confidence = "medium"
    else:
        confidence = "low"

    value_bets: list[ValueBet] = []

    for bookmaker_key, odds_list in odds_by_bookmaker.items():
        if len(odds_list) != len(outcome_keys):
            continue

        for i, odds in enumerate(odds_list):
            consensus_prob = fair_probs[i]
            impl_prob = implied_probability(odds)
            value = value_calculation(consensus_prob, odds)

            if value >= min_value:
                kelly = kelly_criterion(consensus_prob, odds)
                value_bets.append(
                    ValueBet(
                        outcome_index=i,
                        outcome_key=outcome_keys[i],
                        bookmaker_key=bookmaker_key,
                        bookmaker_odds=odds,
                        consensus_prob=round(consensus_prob, 5),
                        implied_prob=round(impl_prob, 5),
                        value_pct=round(value, 5),
                        kelly_full=round(kelly, 5),
                        edge_confidence=confidence,
                    )
                )

    value_bets.sort(key=lambda vb: vb.value_pct, reverse=True)
    return value_bets
