"""
Configuración central del logging.

Dos formatos:
- `text`: legible para desarrollo (timestamp level logger: msg [req=X job=Y]).
- `json`: una línea por record con todos los campos. Diseñado para que un
  log shipper (vector, fluent-bit, etc.) lo parsee sin reglas custom.

El filter `_ContextFilter` inyecta `request_id` y `job_run_id` en cada
record desde los contextvars, así no hay que pasarlos manualmente.

Uso:
    configure_logging(level="INFO", fmt="json")

Llamado una sola vez al inicio del proceso (lifespan startup).
"""

import logging
import sys

from pythonjsonlogger.json import JsonFormatter

from app.log_context import get_job_run_id, get_request_id


class _ContextFilter(logging.Filter):
    """Adjunta request_id y job_run_id (si existen) a cada LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        record.job_run_id = get_job_run_id() or "-"
        return True


class _TextFormatter(logging.Formatter):
    """Formato legible: incluye context IDs solo si no son '-'."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        ctx_parts = []
        rid = getattr(record, "request_id", "-")
        jid = getattr(record, "job_run_id", "-")
        if rid != "-":
            ctx_parts.append(f"req={rid}")
        if jid != "-":
            ctx_parts.append(f"job={jid}")
        if ctx_parts:
            base = f"{base} [{' '.join(ctx_parts)}]"
        return base


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    """
    Configura el root logger. Idempotente: si ya hay handlers, los reemplaza.

    Args:
        level: nivel mínimo (DEBUG, INFO, WARNING, ERROR).
        fmt: 'text' (dev) o 'json' (prod / log shipping).
    """
    root = logging.getLogger()
    # Limpia handlers previos para que `--reload` no acumule duplicados.
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ContextFilter())

    if fmt == "json":
        formatter = JsonFormatter(
            "{asctime}{levelname}{name}{message}{request_id}{job_run_id}",
            style="{",
            rename_fields={"levelname": "level", "asctime": "timestamp"},
        )
    else:
        formatter = _TextFormatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Quiet down noisy loggers que no aportan en INFO.
    # SQLAlchemy echo lo controla DEBUG=true en config; este solo recorta.
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(
        "DEBUG" if level.upper() == "DEBUG" else "WARNING"
    )
    logging.getLogger("apscheduler").setLevel("INFO")
