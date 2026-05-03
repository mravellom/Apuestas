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


def value_calculation_net(
    fair_probability: float, decimal_odds: float, commission_pct: float = 0.0
) -> float:
    """
    EV después de restar comisión del broker sobre la ganancia.

    Modelo de comisión: broker cobra `commission_pct` sobre profit (no sobre stake).
    - Bet $1 pierde: −$1 (sin comisión)
    - Bet $1 gana: +(odds − 1) × (1 − c) neto

    EV_neto = p × (odds − 1) × (1 − c) − (1 − p)
            = p × odds − 1 − p × (odds − 1) × c
    """
    if commission_pct <= 0:
        return value_calculation(fair_probability, decimal_odds)
    b = decimal_odds - 1.0
    return fair_probability * b * (1.0 - commission_pct) - (1.0 - fair_probability)


def kelly_criterion_net(
    probability: float, decimal_odds: float, commission_pct: float = 0.0
) -> float:
    """
    Kelly ajustado por comisión. Usa odds efectivas post-comisión:
        odds_efectiva = 1 + (odds − 1) × (1 − c)
    y aplica Kelly estándar con esa odd.
    """
    if decimal_odds <= 1.0:
        return 0.0
    if commission_pct <= 0:
        return kelly_criterion(probability, decimal_odds)
    effective_odds = 1.0 + (decimal_odds - 1.0) * (1.0 - commission_pct)
    return kelly_criterion(probability, effective_odds)


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
    means, _ = consensus_probability_with_std(
        odds_by_bookmaker, sharp_bookmakers, sharp_weight
    )
    return means


def consensus_probability_with_std(
    odds_by_bookmaker: dict[str, list[float]],
    sharp_bookmakers: set[str] | None = None,
    sharp_weight: float = 2.0,
) -> tuple[list[float], list[float]]:
    """
    Variante del consenso que retorna también el **standard error** por outcome.

    El SE captura la incertidumbre del estimador del consenso: cuando los libros
    coinciden mucho, SE → 0 (consenso confiable). Cuando difieren, SE crece.
    Se usa luego para ajustar Kelly por incertidumbre vía
    `kelly_criterion_uncertainty_adjusted`.

    Cálculo:
      mean = mean ponderado de fair_probs entre books (mismo que `consensus_probability`)
      var_pop = varianza ponderada poblacional
      eff_n = (Σw)² / Σw²  (Kish's effective sample size)
      SE = sqrt(var_pop / eff_n)

    Returns:
        (means, stds) — listas paralelas con el consenso y su SE por outcome.
    """
    if not odds_by_bookmaker:
        raise ValueError("No bookmaker odds provided")

    sharp_bookmakers = sharp_bookmakers or set()
    num_outcomes = len(next(iter(odds_by_bookmaker.values())))

    samples_per_outcome: list[list[tuple[float, float]]] = [
        [] for _ in range(num_outcomes)
    ]
    for bookmaker, odds_list in odds_by_bookmaker.items():
        if len(odds_list) != num_outcomes:
            continue
        fair_probs = odds_to_fair_probs(odds_list)
        weight = sharp_weight if bookmaker in sharp_bookmakers else 1.0
        for i, prob in enumerate(fair_probs):
            samples_per_outcome[i].append((prob, weight))

    if not any(samples_per_outcome):
        raise ValueError("No valid bookmaker data")

    means: list[float] = []
    stds: list[float] = []
    for samples in samples_per_outcome:
        if not samples:
            means.append(0.0)
            stds.append(0.0)
            continue
        total_w = sum(w for _, w in samples)
        if total_w <= 0:
            means.append(0.0)
            stds.append(0.0)
            continue
        mean = sum(p * w for p, w in samples) / total_w
        var_pop = sum(w * (p - mean) ** 2 for p, w in samples) / total_w
        sum_w_sq = sum(w * w for _, w in samples)
        eff_n = (total_w * total_w) / sum_w_sq if sum_w_sq > 0 else len(samples)
        se = (var_pop / eff_n) ** 0.5 if eff_n > 0 else 0.0
        means.append(mean)
        stds.append(se)

    return means, stds


def kelly_criterion_uncertainty_adjusted(
    probability: float,
    decimal_odds: float,
    prob_std: float,
    commission_pct: float = 0.0,
) -> float:
    """
    Kelly ajustado por incertidumbre en `probability`.

    Cuando `probability` es un estimador con error estándar `prob_std`, apostar
    el Kelly completo es sub-óptimo: una fracción del edge aparente puede ser
    ruido. La corrección estándar (Vince/Sinclair) es:

        f_adjusted = f_kelly × max(0, 1 − Var[edge] / E[edge]²)

    donde:
        E[edge] = p · odds − 1                         (EV neto si sin comisión)
        Var[edge] = odds² · σ²_p                       (linealización: edge es lineal en p)

    Si σ_edge ≥ E[edge] (la incertidumbre supera al edge esperado) → f = 0:
    no apostar.

    Args:
        probability: estimador de la probabilidad real.
        decimal_odds: cuota decimal del libro.
        prob_std: standard error del estimador `probability`.
        commission_pct: comisión sobre profit (0-1).

    Returns:
        Fracción Kelly óptima bajo incertidumbre, o 0 si la señal es ruido.
    """
    f_kelly = kelly_criterion_net(probability, decimal_odds, commission_pct)
    if f_kelly <= 0:
        return 0.0
    if prob_std <= 0:
        return f_kelly

    edge = value_calculation_net(probability, decimal_odds, commission_pct)
    if edge <= 0:
        return 0.0

    # Linealización: edge = p·odds_eff − 1 → ∂edge/∂p = odds_eff. Para preservar
    # consistencia con el Kelly que ya usa odds efectivas post-comisión, usamos
    # la misma cuota efectiva aquí.
    effective_odds = (
        1.0 + (decimal_odds - 1.0) * (1.0 - commission_pct)
        if commission_pct > 0
        else decimal_odds
    )
    sigma_edge = effective_odds * prob_std
    shrinkage = max(0.0, 1.0 - (sigma_edge * sigma_edge) / (edge * edge))
    return f_kelly * shrinkage


def calculate_roi(total_profit: float, total_staked: float) -> float:
    """Calcula ROI como porcentaje."""
    if total_staked <= 0:
        return 0.0
    return (total_profit / total_staked) * 100.0
