"""
Steam detection: detección de movimientos rápidos en libros sharp.

# Definición operativa

"Steam" = movimiento brusco en libros sharp (Pinnacle, Betfair, etc.) que
todavía no se ha propagado a libros soft. Cuando los sharps mueven, los soft
tardan minutos en ajustar. Si detectás una value bet contra un soft book DURANTE
un steam move, esa "value" puede ser simplemente cuota stale a punto de corregirse.

# Implicación práctica

`is_steam=True` en una Opportunity NO significa que sea mala — significa que la
ventana de ejecución es corta. Útil para:
  - Priorizar señales en notificaciones
  - Filtrar análisis ex-post (CLV de steam vs no-steam debería diferir)
  - Decidir manualmente si vale la pena ejecutar antes de que el soft mueva

# Algoritmo

Para un outcome dado:
  1. Tomar la cuota más reciente de cada libro sharp.
  2. Tomar la cuota de hace `window_minutes` (o el snapshot más antiguo dentro del window).
  3. Computar |Δ probabilidad implícita| = |1/p_old − 1/p_new|.
  4. Si CUALQUIER sharp tuvo Δ ≥ velocity_threshold → steam.

Defaults:
  - velocity_threshold = 0.02  (2% de probabilidad implícita)
  - window_minutes = 5

Refinable después con datos: ajustar umbrales por sport, requerir K libros
movidos en el mismo sentido, etc.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookmaker import Bookmaker
from app.models.market import Odds


@dataclass
class SteamSignal:
    is_steam: bool
    max_velocity: float          # |Δ implícita| del libro que más se movió
    moved_books: list[str]       # books que cruzaron el umbral
    direction: str | None = None  # "shortening" si subió la prob, "drifting" si bajó


async def detect_steam_signal(
    db: AsyncSession,
    outcome_id: int,
    velocity_threshold: float = 0.02,
    window_minutes: int = 5,
) -> SteamSignal:
    """Computa el steam signal para un outcome usando libros sharp.

    Excluye al sharp_books del propio bookmaker de la oportunidad — el caller
    decide si es relevante. Acá solo medimos qué hicieron los sharps.

    Returns:
        SteamSignal con is_steam=True si algún sharp se movió ≥ threshold.
    """
    sharps_result = await db.execute(
        select(Bookmaker.id, Bookmaker.key).where(Bookmaker.is_sharp.is_(True))
    )
    sharps = list(sharps_result.all())
    if not sharps:
        return SteamSignal(is_steam=False, max_velocity=0.0, moved_books=[])

    sharp_ids = [bm_id for bm_id, _ in sharps]
    sharp_key_by_id = {bm_id: key for bm_id, key in sharps}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    window_start = now - timedelta(minutes=window_minutes)

    rows = (
        await db.execute(
            select(Odds.bookmaker_id, Odds.price, Odds.captured_at)
            .where(
                Odds.outcome_id == outcome_id,
                Odds.bookmaker_id.in_(sharp_ids),
                Odds.captured_at >= window_start,
            )
            .order_by(Odds.bookmaker_id, Odds.captured_at)
        )
    ).all()

    by_book: dict[int, list[tuple[float, datetime]]] = {}
    for bm_id, price, captured_at in rows:
        by_book.setdefault(bm_id, []).append((float(price), captured_at))

    max_velocity = 0.0
    moved_books: list[str] = []
    direction_signed = 0.0  # signo del libro que más se movió

    for bm_id, samples in by_book.items():
        if len(samples) < 2:
            continue
        oldest_price, _ = samples[0]
        newest_price, _ = samples[-1]
        if oldest_price <= 0 or newest_price <= 0:
            continue
        delta_prob = (1.0 / newest_price) - (1.0 / oldest_price)
        velocity = abs(delta_prob)
        if velocity >= velocity_threshold:
            moved_books.append(sharp_key_by_id[bm_id])
        if velocity > max_velocity:
            max_velocity = velocity
            direction_signed = delta_prob

    if not moved_books:
        return SteamSignal(is_steam=False, max_velocity=max_velocity, moved_books=[])

    direction = "shortening" if direction_signed > 0 else "drifting"
    return SteamSignal(
        is_steam=True,
        max_velocity=max_velocity,
        moved_books=moved_books,
        direction=direction,
    )
