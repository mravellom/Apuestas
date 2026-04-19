"""Detector de value bets."""

import statistics
from dataclasses import dataclass

from app.core.formulas import (
    consensus_probability,
    implied_probability,
    kelly_criterion,
    kelly_criterion_net,
    odds_to_fair_probs,
    value_calculation,
    value_calculation_net,
)

MIN_ODDS = 1.30
MAX_ODDS = 10.0
MAX_ODDS_CV = 0.15  # coef. de variación máximo por outcome


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


def _outcome_odds_dispersed(odds_by_bookmaker: dict[str, list[float]], outcome_idx: int) -> bool:
    """Detecta dispersión excesiva en un outcome — señal de error de datos."""
    prices = [ol[outcome_idx] for ol in odds_by_bookmaker.values()]
    if len(prices) < 3:
        return True
    mean = statistics.mean(prices)
    if mean <= 0:
        return True
    cv = statistics.stdev(prices) / mean
    return cv > MAX_ODDS_CV


def detect_value_bets(
    odds_by_bookmaker: dict[str, list[float]],
    outcome_keys: list[str],
    sharp_bookmakers: set[str] | None = None,
    min_value: float = 0.05,
    min_bookmakers: int = 5,
) -> list[ValueBet]:
    """
    Detecta value bets en un mercado con filtros anti-basura.

    Filtros aplicados:
    - min_bookmakers: consenso mínimo robusto (default 5)
    - odds range: descarta favoritos extremos (<1.30) y longshots (>10.0)
    - dispersión: descarta outcomes con coef. variación > 15%
    - min_value: EV mínimo 5%

    Args:
        odds_by_bookmaker: {bookmaker_key: [odds per outcome]}
        outcome_keys: ["home", "draw", "away"]
        sharp_bookmakers: bookmakers con mayor peso en consenso
        min_value: porcentaje mínimo de value para considerar (default 5%)
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
            if odds < MIN_ODDS or odds > MAX_ODDS:
                continue

            if _outcome_odds_dispersed(odds_by_bookmaker, i):
                continue

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


def detect_value_bets_vs_reference(
    odds_by_bookmaker: dict[str, list[float]],
    outcome_keys: list[str],
    reference_bookmaker: str,
    min_value: float = 0.02,
    commission_by_bookmaker: dict[str, float] | None = None,
) -> list[ValueBet]:
    """
    Detecta value bets usando un bookmaker de referencia como "cuota justa".

    Útil cuando sólo tienes 2-3 casas accesibles: no hay consenso robusto,
    pero sí tienes un sharp (Pinnacle) cuyas cuotas de-viguiadas son una buena
    estimación de la probabilidad real.

    Args:
        odds_by_bookmaker: {bookmaker_key: [odds per outcome]}
        outcome_keys: ["home", "draw", "away"]
        reference_bookmaker: clave del book sharp (ej. "pinnacle")
        min_value: EV mínimo (default 2% — más bajo que consenso porque la
                   señal es más ruidosa).

    Returns:
        Lista de ValueBet ordenada por value_pct descendente.
        Excluye al bookmaker de referencia (value vs sí mismo es 0).
    """
    if reference_bookmaker not in odds_by_bookmaker:
        return []

    reference_odds = odds_by_bookmaker[reference_bookmaker]
    if len(reference_odds) != len(outcome_keys):
        return []

    fair_probs = odds_to_fair_probs(reference_odds)
    commission_by_bookmaker = commission_by_bookmaker or {}

    value_bets: list[ValueBet] = []
    for bookmaker_key, odds_list in odds_by_bookmaker.items():
        if bookmaker_key == reference_bookmaker:
            continue
        if len(odds_list) != len(outcome_keys):
            continue

        commission = commission_by_bookmaker.get(bookmaker_key, 0.0)

        for i, odds in enumerate(odds_list):
            if odds < MIN_ODDS or odds > MAX_ODDS:
                continue

            fair_prob = fair_probs[i]
            impl_prob = implied_probability(odds)
            value = value_calculation_net(fair_prob, odds, commission)

            if value >= min_value:
                kelly = kelly_criterion_net(fair_prob, odds, commission)
                value_bets.append(
                    ValueBet(
                        outcome_index=i,
                        outcome_key=outcome_keys[i],
                        bookmaker_key=bookmaker_key,
                        bookmaker_odds=odds,
                        consensus_prob=round(fair_prob, 5),
                        implied_prob=round(impl_prob, 5),
                        value_pct=round(value, 5),
                        kelly_full=round(kelly, 5),
                        edge_confidence="reference",
                    )
                )

    value_bets.sort(key=lambda vb: vb.value_pct, reverse=True)
    return value_bets
