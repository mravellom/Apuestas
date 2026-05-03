"""
Portfolio Kelly: asignación de stakes en un batch de señales simultáneas.

# Problema

`detect_value_bets` produce N oportunidades simultáneas en un ciclo de detección.
Si aplicamos Kelly individual a cada una y sumamos, podemos exceder un % razonable
del bankroll (ej. 5 señales × 5% Kelly = 25% expuesto en un día).

# Algoritmo

1. **Group by match** (decisión de diseño): legs del mismo partido están
   correlacionados (un mismo match solo tiene un ganador). Conservamos solo la
   leg con mayor `raw_kelly` por match — el resto se descarta del paper trading
   pero las Opportunities sí se persisten para visibilidad.

2. **Per-bet sizing**: aplicar Kelly fraccionado (1/4 default) y cap por bet.

3. **Constraint binding**: si la suma supera `max_total_exposure`, escalar
   proporcionalmente. Para stakes chicos (típicos en fractional Kelly), proporcional
   scaling es ~95% del óptimo log-utility con bets independientes.

# Por qué no log-optimal exacto

El óptimo log-utility bajo restricción se resuelve con bisección sobre el
multiplicador de Lagrange. Para stakes < 5%, la diferencia con proporcional
scaling es < 5%. Migrar a la versión exacta es un swap quirúrgico cuando los
datos lo justifiquen.
"""

from dataclasses import dataclass


@dataclass
class PortfolioBet:
    """Input para el optimizador: una señal candidata pre-sizing."""

    bet_id: str            # identificador único (ej. "opp_42")
    match_id: int          # para agrupar legs correlacionados
    raw_kelly: float       # Kelly por incertidumbre, 0..1


@dataclass
class PortfolioAllocation:
    """Output: stake fraccional final asignado, o 0 si descartada."""

    bet_id: str
    stake: float           # fracción del bankroll, 0..max_per_bet
    skipped: bool
    reason: str = ""


def allocate_portfolio(
    bets: list[PortfolioBet],
    *,
    available_exposure: float,
    kelly_fraction: float = 0.25,
    per_bet_cap: float = 0.05,
) -> list[PortfolioAllocation]:
    """
    Asigna stakes para un batch de señales simultáneas.

    Args:
        bets: señales candidatas con su `raw_kelly` ya calculado
            (típicamente vía `kelly_criterion_uncertainty_adjusted`).
        available_exposure: budget total disponible (max_total_exposure − ya_pendiente).
            Si ≤ 0, todas se descartan.
        kelly_fraction: fracción del Kelly a aplicar (default 1/4).
        per_bet_cap: tope absoluto por bet (default 5% del bankroll).

    Returns:
        Lista de PortfolioAllocation alineada por `bet_id` con la entrada.
        Allocations con `skipped=True` y `stake=0` cuando se descarta la bet
        (correlación, exposure full, o Kelly base = 0).
    """
    by_id = {b.bet_id: b for b in bets}

    if available_exposure <= 0:
        return [
            PortfolioAllocation(
                bet_id=b.bet_id, stake=0.0, skipped=True, reason="exposure_full"
            )
            for b in bets
        ]

    # Paso 1: agrupar por match, conservar solo la leg de mayor Kelly.
    best_per_match: dict[int, PortfolioBet] = {}
    for b in bets:
        if b.raw_kelly <= 0:
            continue
        existing = best_per_match.get(b.match_id)
        if existing is None or b.raw_kelly > existing.raw_kelly:
            best_per_match[b.match_id] = b

    surviving_ids = {b.bet_id for b in best_per_match.values()}

    # Paso 2: per-bet sizing (fractional Kelly + cap por bet).
    desired: dict[str, float] = {}
    for b in best_per_match.values():
        d = min(b.raw_kelly * kelly_fraction, per_bet_cap)
        if d > 0:
            desired[b.bet_id] = d

    # Paso 3: si suma > available, escalar proporcional.
    total_desired = sum(desired.values())
    if total_desired > available_exposure and total_desired > 0:
        scale = available_exposure / total_desired
        desired = {bid: stake * scale for bid, stake in desired.items()}

    # Construir allocations preservando orden de entrada.
    allocations: list[PortfolioAllocation] = []
    for b in bets:
        if b.bet_id in desired:
            allocations.append(
                PortfolioAllocation(bet_id=b.bet_id, stake=desired[b.bet_id], skipped=False)
            )
        elif b.raw_kelly <= 0:
            allocations.append(
                PortfolioAllocation(
                    bet_id=b.bet_id, stake=0.0, skipped=True, reason="zero_kelly"
                )
            )
        elif b.bet_id not in surviving_ids:
            allocations.append(
                PortfolioAllocation(
                    bet_id=b.bet_id,
                    stake=0.0,
                    skipped=True,
                    reason="correlated_leg_dropped",
                )
            )
        else:
            # Descartado por scaling (no esperado si el algoritmo está bien).
            allocations.append(
                PortfolioAllocation(
                    bet_id=b.bet_id, stake=0.0, skipped=True, reason="scaled_out"
                )
            )
    return allocations
