"""Métricas Prometheus para jobs del scheduler.

Las latencias HTTP y las etiquetas por endpoint las emite
`prometheus-fastapi-instrumentator` automáticamente vía /metrics. Este módulo
añade lo que el instrumentator no cubre:
  - duración y resultado de cada job periódico
  - contador de fallos consecutivos por job (para alerting / dashboards)

Además, asigna un `job_run_id` por ejecución y lo deja en contextvars
para que el logging estructurado pueda correlacionar todas las líneas que
emite ese run.

Integración con circuit breaker: en cada error/ok consulta
`JobHealthTracker` y dispara `send_admin_alert` cuando el conteo cruza
el umbral o cuando hay recovery.
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from functools import wraps

from prometheus_client import Counter, Gauge, Histogram

from app.admin_alerter import send_admin_alert
from app.config import settings
from app.job_health import configure_from_settings, get_tracker
from app.log_context import job_run_id_var

logger = logging.getLogger(__name__)

JOB_DURATION = Histogram(
    "valuebet_job_duration_seconds",
    "Duración de un job del scheduler, en segundos.",
    labelnames=("job_name",),
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)

JOB_RUNS = Counter(
    "valuebet_job_runs_total",
    "Número de ejecuciones por job y resultado (ok|error).",
    labelnames=("job_name", "status"),
)

# Útil para alerting Prometheus: alert si > 0 sostenido. Como la alerta
# por Telegram ya cubre el operador, este gauge sirve para dashboards.
JOB_CONSECUTIVE_FAILURES = Gauge(
    "valuebet_job_consecutive_failures",
    "Fallos consecutivos por job (resetea a 0 con la próxima ejecución ok).",
    labelnames=("job_name",),
)


# Sincroniza el threshold del tracker con settings al importar el módulo.
configure_from_settings(settings.JOB_FAILURE_ALERT_THRESHOLD)


@asynccontextmanager
async def track_job(job_name: str):
    """
    Mide duración, clasifica resultado, propaga `job_run_id` al contexto
    de logging, y dispara alertas admin cuando hay rachas de fallos.
    """
    run_id = uuid.uuid4().hex[:8]
    token = job_run_id_var.set(run_id)
    start = time.perf_counter()
    status = "ok"
    tracker = get_tracker()
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        duration = time.perf_counter() - start
        JOB_DURATION.labels(job_name=job_name).observe(duration)
        JOB_RUNS.labels(job_name=job_name, status=status).inc()

        if status == "ok":
            had_alert = tracker.record_success(job_name)
            JOB_CONSECUTIVE_FAILURES.labels(job_name=job_name).set(0)
            if had_alert:
                # Recovery: cerramos el incidente.
                await send_admin_alert(
                    f"✅ Job '{job_name}' recuperado tras racha de fallos."
                )
        else:
            should_alert = tracker.record_failure(job_name)
            JOB_CONSECUTIVE_FAILURES.labels(job_name=job_name).set(
                tracker.consecutive_failures(job_name)
            )
            if should_alert:
                await send_admin_alert(
                    f"🔥 Job '{job_name}' falló {tracker.threshold} veces "
                    f"consecutivas. Revisa logs (run_id={run_id})."
                )

        job_run_id_var.reset(token)


def tracked_job(job_name: str):
    """Decorador: envuelve una corrutina de scheduler con `track_job`."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async with track_job(job_name):
                return await func(*args, **kwargs)
        return wrapper
    return decorator
