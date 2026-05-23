"""SSE endpoint para push de nuevas oportunidades al frontend.

Auth vía `?token=...` en query string. El browser EventSource API no
permite headers HTTP custom (limitación del estándar) — JWT en query es
el patrón estándar para SSE autenticado. El token es el mismo JWT del
header `Authorization: Bearer`, solo cambia el transporte.

**Latency objetivo**: <2s entre que el job inserta la oportunidad y el
frontend la muestra. Reemplaza el polling cada 60s del listado.
"""

import asyncio
import json
import logging
import uuid as _uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models.user import User
from app.notifications.event_bus import bus

logger = logging.getLogger(__name__)

router = APIRouter()

# Heartbeat cada 15s para evitar que proxies/CDN (Cloudflare, nginx) cierren
# la conexión por idle. SSE comments (líneas que empiezan con `:`) son legales
# por la spec y el cliente las ignora.
HEARTBEAT_SECONDS = 15.0


async def _authenticate_token(token: str) -> User:
    """Mismo flujo que `get_current_user` pero leyendo token de query string
    en vez del header Authorization."""
    creds_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token",
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id = payload.get("sub")
        if not user_id:
            raise creds_exc
    except JWTError:
        raise creds_exc

    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.id == _uuid.UUID(user_id))
        )
        user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise creds_exc
    return user


@router.get("/stream/opportunities")
async def stream_opportunities(
    request: Request,
    token: str = Query(
        ...,
        description=(
            "JWT bearer — mismo valor del header Authorization. Va en query "
            "porque el browser EventSource no admite headers custom."
        ),
    ),
):
    """Server-Sent Events: emite un ping cuando se detecta una oportunidad nueva.

    Eventos emitidos:
        event: arbitrage    →   data: {"id": <int>}
        event: value        →   data: {"id": <int>}

    El payload es mínimo (solo el ID). El frontend reacciona refetcheando
    la lista — el `/api/v1/arbitrage/?status=active` y
    `/api/v1/opportunities/history` ya tienen toda la lógica de
    filtrado/auth/format/sort.
    """
    user = await _authenticate_token(token)
    logger.info("SSE connect: user=%s", user.email)

    async def event_generator():
        queue = await bus.subscribe()
        try:
            # Línea inicial (SSE comment) — confirma conexión al cliente
            yield ":connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=HEARTBEAT_SECONDS
                    )
                    yield (
                        f"event: {event['type']}\n"
                        f"data: {json.dumps(event['data'])}\n\n"
                    )
                except asyncio.TimeoutError:
                    # Heartbeat para mantener viva la conexión
                    yield ":heartbeat\n\n"
        except asyncio.CancelledError:
            # cliente desconectó — flujo normal
            pass
        finally:
            await bus.unsubscribe(queue)
            logger.info("SSE disconnect: user=%s", user.email)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # Anti-buffering de nginx si en algún día se sirve detrás de uno
            "X-Accel-Buffering": "no",
        },
    )
