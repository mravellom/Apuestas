"""
Variables de contexto que viajan con cada request HTTP o ejecución de job.

`contextvars` mantiene aislamiento por tarea async — el `request_id` que
ponga el middleware queda disponible para todo el código que la request
ejecute (handlers, services, queries) sin tener que pasarlo explícito.

Quien produce los IDs:
- request_id: `RequestLoggingMiddleware` por cada HTTP request.
- job_run_id: `track_job` (en `app/metrics.py`) por cada ejecución de job.

Quien los consume: el filter de logging (en `logging_config.py`) los
inyecta como atributos del LogRecord para que aparezcan en cada línea.
"""

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
job_run_id_var: ContextVar[str | None] = ContextVar("job_run_id", default=None)


def get_request_id() -> str | None:
    return request_id_var.get()


def get_job_run_id() -> str | None:
    return job_run_id_var.get()
