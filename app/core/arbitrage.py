"""
Detector de oportunidades de arbitraje (surebets).

Condición: si para un mercado (ej. H2H con 3 outcomes) tomamos la MEJOR
cuota de cada outcome entre todas las casas, y la suma de probabilidades
implícitas es < 1, existe arbitraje con ganancia garantizada.

# Precisión numérica (bug #6)

Este módulo opera en `float` porque las cuotas vienen como float desde
JSON/Odds-API, y las operaciones aritméticas (sumas, divisiones) con float
son suficientes para detección: error de redondeo < 1e-15, irrelevante
frente al tamaño de las cuotas (~1-20).

El boundary a Decimal ocurre al guardar en DB (`ArbitrageOpportunity`),
donde siempre usamos `Decimal(str(float_value))` — preserva la
representación del float exactamente sin perder precisión.
Nunca usar `Decimal(float_value)` directamente.

# Normalización de stake_pct (bug #7)

Los `stake_pct` se computan como fracciones que idealmente suman 1.0, pero
el redondeo de float puede dar 0.99999... o 1.00001. El residuo se reparte
uniformemente entre todos los legs para que `sum(stake_pct) == 1.0` exacto.
Sin esto, ejecutar el arb deja unos centavos sin asignar o los sobrestakea,
invalidando marginalmente el balance del surebet.
"""

from dataclasses import dataclass, field


@dataclass
class ArbLeg:
    """Una pata del arbitraje: qué apostar, dónde, y cuánto."""
    outcome_key: str
    outcome_name: str
    bookmaker_key: str
    best_odds: float
    implied_prob: float
    stake_pct: float  # fracción del capital total (0-1)


@dataclass
class ArbOpportunity:
    """Oportunidad de arbitraje completa."""
    legs: list[ArbLeg] = field(default_factory=list)
    total_implied: float = 0.0  # sum(1/best_odds) — must be < 1
    profit_pct: float = 0.0     # (1/total_implied - 1) * 100
    num_outcomes: int = 0

    @property
    def is_valid(self) -> bool:
        return self.total_implied < 1.0 and self.profit_pct > 0


def find_best_odds(
    odds_by_bookmaker: dict[str, list[float]],
    outcome_keys: list[str],
) -> list[tuple[float, str]]:
    """
    Para cada outcome, encuentra la mejor cuota y qué bookmaker la ofrece.
    Returns: [(best_odds, bookmaker_key), ...] por outcome.
    """
    num_outcomes = len(outcome_keys)
    best: list[tuple[float, str]] = [(0.0, "")] * num_outcomes

    for bk_key, odds_list in odds_by_bookmaker.items():
        if len(odds_list) != num_outcomes:
            continue
        for i, odds in enumerate(odds_list):
            if odds > best[i][0]:
                best[i] = (odds, bk_key)

    return best


def detect_arbitrage(
    odds_by_bookmaker: dict[str, list[float]],
    outcome_keys: list[str],
    outcome_names: list[str] | None = None,
    min_profit_pct: float = 0.5,
    min_bookmakers: int = 5,
    commission_by_bookmaker: dict[str, float] | None = None,
) -> ArbOpportunity | None:
    """
    Detecta si existe arbitraje en un mercado.

    Args:
        odds_by_bookmaker: {bookmaker_key: [odds per outcome]}
        outcome_keys: ["home", "draw", "away"]
        outcome_names: ["Home Win", "Draw", "Away Win"] (display names)
        min_profit_pct: beneficio mínimo para considerar (default 0.5%)
        min_bookmakers: mínimo de bookmakers para considerar

    Returns:
        ArbOpportunity si existe, None si no.
    """
    if len(odds_by_bookmaker) < min_bookmakers:
        return None

    if outcome_names is None:
        outcome_names = outcome_keys

    commission_by_bookmaker = commission_by_bookmaker or {}

    best = find_best_odds(odds_by_bookmaker, outcome_keys)

    # Verify all outcomes have valid odds
    if any(odds <= 1.0 or bk == "" for odds, bk in best):
        return None

    # Adjust odds for broker commission: only the winning leg pays commission,
    # and exactly one leg wins. Effective payout per leg:
    #   effective_odds = 1 + (odds − 1) × (1 − c_book)
    effective_best = [
        (1.0 + (odds - 1.0) * (1.0 - commission_by_bookmaker.get(bk, 0.0)), bk)
        for odds, bk in best
    ]

    # Core arbitrage condition with commission: sum(1/effective_odds) < 1
    total_implied = sum(1.0 / odds for odds, _ in effective_best)

    if total_implied >= 1.0:
        return None

    profit_pct = (1.0 / total_implied - 1.0) * 100.0

    if profit_pct < min_profit_pct:
        return None

    # Calcula stakes proporcionales a la prob. implícita efectiva (post-comisión)
    # para que el payout sea equivalente en cada outcome.
    # Paso 1: raw stake_pct = prob_implícita / sum(prob_implícita) para cada leg.
    raw_stake_pcts = [
        (1.0 / eff_odds) / total_implied for eff_odds, _ in effective_best
    ]

    # Paso 2: reparto uniforme del residuo de redondeo float (bug #7). Sin
    # esto, sum(stake_pct) puede ser 0.9999... o 1.0001, haciendo que al
    # stakear con capital real queden centavos flotando o sobre-stakeados.
    # Repartir entre todos los legs evita el sesgo de presentación de
    # cargarle todo al último leg (que depende del orden de outcome_keys).
    residual = 1.0 - sum(raw_stake_pcts)
    per_leg = residual / len(raw_stake_pcts)
    raw_stake_pcts = [p + per_leg for p in raw_stake_pcts]

    legs = []
    for i, ((odds, bk_key), (eff_odds, _)) in enumerate(zip(best, effective_best)):
        eff_imp = 1.0 / eff_odds
        legs.append(ArbLeg(
            outcome_key=outcome_keys[i],
            outcome_name=outcome_names[i] if i < len(outcome_names) else outcome_keys[i],
            bookmaker_key=bk_key,
            best_odds=odds,
            implied_prob=round(eff_imp, 5),
            stake_pct=round(raw_stake_pcts[i], 5),
        ))

    return ArbOpportunity(
        legs=legs,
        total_implied=round(total_implied, 6),
        profit_pct=round(profit_pct, 3),
        num_outcomes=len(outcome_keys),
    )


def calculate_stakes(arb: ArbOpportunity, total_capital: float) -> list[dict]:
    """
    Calcula stakes concretos dado un capital total.

    Returns:
        [{"outcome": "Home", "bookmaker": "bet365", "odds": 2.10,
          "stake": 47.62, "payout": 100.0}, ...]
    """
    result = []
    for leg in arb.legs:
        stake = total_capital * leg.stake_pct
        payout = stake * leg.best_odds
        result.append({
            "outcome": leg.outcome_name,
            "bookmaker": leg.bookmaker_key,
            "odds": leg.best_odds,
            "stake": round(stake, 2),
            "payout": round(payout, 2),
        })
    return result
