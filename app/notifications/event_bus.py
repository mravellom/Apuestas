"""In-process pub/sub para SSE.

Cuando `detect_arbitrage_job` o `detect_value_job` insertan oportunidades
nuevas, publican un evento aquí; las conexiones SSE activas reciben el
ping y el frontend refetchea su lista. La perceptibilidad de "arb existe
→ usuario lo ve" baja de ~60s (polling) a ~1s.

**Single-process.** Si el día de mañana el API escala a múltiples workers
(uvicorn `--workers N`), cada worker tiene su propio bus → los publishers
en worker A no llegan a subscribers en worker B. Fix: swap por Redis Pub/Sub
(Redis ya está disponible en el compose). Por ahora single-process es
suficiente y mantiene la complejidad baja.

**Best-effort.** Si una queue está full (subscriber lento), se descarta el
evento para ese subscriber — el publisher (job) NUNCA bloquea. El subscriber
en práctica no llega a llenarse porque el frontend solo dispara un refetch
liviano por evento.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Máximo de eventos pendientes por subscriber antes de descartar. Generoso:
# un subscriber sano consume en <1s; si acumula 100 es porque está roto.
_SUBSCRIBER_QUEUE_MAXSIZE = 100


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def publish(self, event_type: str, data: Any) -> None:
        """Emite un evento a todos los subscribers actuales. No bloquea."""
        async with self._lock:
            subs = list(self._subscribers)
        event = {"type": event_type, "data": data}
        for q in subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "SSE queue full for a subscriber; dropped event %s",
                    event_type,
                )

    async def subscribe(self) -> asyncio.Queue:
        """Registra un subscriber. El caller debe llamar `unsubscribe` al cerrar."""
        q: asyncio.Queue = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAXSIZE)
        async with self._lock:
            self._subscribers.append(q)
            count = len(self._subscribers)
        logger.debug("SSE subscriber added (total=%d)", count)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            try:
                self._subscribers.remove(q)
                count = len(self._subscribers)
            except ValueError:
                return
        logger.debug("SSE subscriber removed (total=%d)", count)

    def subscriber_count(self) -> int:
        """Solo para observabilidad (`/healthz`, métricas). No lockea."""
        return len(self._subscribers)


# Singleton — importar como `from app.notifications.event_bus import bus`
bus = EventBus()
