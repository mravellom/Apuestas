"""Middleware HTTP: correlation ID + access log."""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.log_context import request_id_var

logger = logging.getLogger("valuebet.access")

# Header estándar de facto para correlation IDs en HTTP. Si el caller ya
# trae uno, lo respetamos para que la traza se concatene a la suya.
_REQUEST_ID_HEADER = "X-Request-ID"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Id corto (8 chars) para legibilidad en consola. Si el cliente
        # envió uno, lo usamos tal cual — la forma es del que llama.
        incoming = request.headers.get(_REQUEST_ID_HEADER)
        request_id = incoming or uuid.uuid4().hex[:8]
        token = request_id_var.set(request_id)

        start = time.perf_counter()
        try:
            response = await call_next(request)
            elapsed_ms = (time.perf_counter() - start) * 1000
            # Eco del header para que el cliente correlacione sus logs.
            response.headers[_REQUEST_ID_HEADER] = request_id
            # Log dentro del scope del contextvar — si lo emitimos tras
            # reset(token), el filter pierde el id.
            logger.info(
                "%s %s %d %.1fms",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )
            return response
        finally:
            request_id_var.reset(token)
