"""
Tracker de salud de jobs: cuenta fallos consecutivos por nombre y decide
cuándo emitir una alerta al admin.

Diseño:
- `record_failure` devuelve True solo en la **transición** que cruza el
  umbral. Mientras siga fallando, devuelve False — el admin recibe una
  alerta, no una por iteración.
- Cuando el job vuelve a `ok`, el contador se resetea y, si había una
  alerta activa, se dispara una segunda alerta de **recovery**.
- En memoria, no persistido. Si el proceso reinicia, el estado se pierde
  — aceptable porque las próximas iteraciones del scheduler reconstruyen
  el conteo en minutos.

No conoce el canal de notificación; solo decide *si* alertar. El despacho
real lo hace `app.admin_alerter`.
"""

from dataclasses import dataclass


@dataclass
class JobHealthState:
    consecutive_failures: int = 0
    alert_active: bool = False


class JobHealthTracker:
    def __init__(self, threshold: int = 3):
        # Umbral mínimo: con 1 cruzas instantáneo, 3 da 3 ciclos de
        # gracia. Configurable vía settings.
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        self.threshold = threshold
        self._states: dict[str, JobHealthState] = {}

    def _state(self, job_name: str) -> JobHealthState:
        if job_name not in self._states:
            self._states[job_name] = JobHealthState()
        return self._states[job_name]

    def record_failure(self, job_name: str) -> bool:
        """
        Incrementa el contador. Devuelve True si esta llamada cruza el
        umbral por primera vez (es decir, debe disparar alerta).
        """
        st = self._state(job_name)
        st.consecutive_failures += 1
        if st.consecutive_failures >= self.threshold and not st.alert_active:
            st.alert_active = True
            return True
        return False

    def record_success(self, job_name: str) -> bool:
        """
        Resetea el contador. Devuelve True si había una alerta activa
        que ahora se "cierra" — útil para mandar mensaje de recovery.
        """
        st = self._state(job_name)
        had_alert = st.alert_active
        st.consecutive_failures = 0
        st.alert_active = False
        return had_alert

    def consecutive_failures(self, job_name: str) -> int:
        return self._state(job_name).consecutive_failures


# Instancia global. Se reconfigura el threshold en `configure_from_settings()`
# si los defaults cambian. No usamos un singleton lazy porque queremos que
# la métrica Prometheus pueda observar el mismo estado.
_tracker = JobHealthTracker()


def get_tracker() -> JobHealthTracker:
    return _tracker


def configure_from_settings(threshold: int) -> None:
    """Reconfigura el threshold global. Idempotente."""
    _tracker.threshold = threshold
