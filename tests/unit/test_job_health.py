"""Tests del circuit breaker de jobs y la integración con `track_job`."""

import pytest

from app.job_health import JobHealthTracker
from app.metrics import JOB_CONSECUTIVE_FAILURES, track_job


class TestJobHealthTracker:
    def test_threshold_must_be_positive(self):
        with pytest.raises(ValueError):
            JobHealthTracker(threshold=0)

    def test_first_failures_dont_alert_below_threshold(self):
        t = JobHealthTracker(threshold=3)
        assert t.record_failure("j") is False
        assert t.record_failure("j") is False
        # En el tercero cruza — devuelve True una sola vez.
        assert t.record_failure("j") is True

    def test_alert_triggers_only_once_per_incident(self):
        t = JobHealthTracker(threshold=2)
        assert t.record_failure("j") is False
        assert t.record_failure("j") is True
        # Mientras siga fallando, NO se vuelve a disparar.
        assert t.record_failure("j") is False
        assert t.record_failure("j") is False

    def test_success_resets_counter_and_signals_recovery(self):
        t = JobHealthTracker(threshold=2)
        t.record_failure("j")
        assert t.record_failure("j") is True
        # Recovery: success tras alerta activa devuelve True una vez.
        assert t.record_success("j") is True
        # Próximo success ya no señala recovery (no había alerta).
        assert t.record_success("j") is False
        # Y el contador está en 0.
        assert t.consecutive_failures("j") == 0

    def test_jobs_isolated_from_each_other(self):
        t = JobHealthTracker(threshold=2)
        t.record_failure("a")
        t.record_failure("a")  # 'a' alerta
        # 'b' no debe alertar porque su contador es 0.
        assert t.record_failure("b") is False
        assert t.consecutive_failures("a") == 2
        assert t.consecutive_failures("b") == 1

    def test_success_without_prior_failure_is_no_op(self):
        t = JobHealthTracker(threshold=3)
        assert t.record_success("j") is False
        assert t.consecutive_failures("j") == 0


class TestTrackJobIntegration:
    """`track_job` debe disparar admin alert tras umbral y recovery."""

    @pytest.fixture(autouse=True)
    def reset_tracker_and_capture_alerts(self, monkeypatch):
        # Aislamos del estado global: tracker fresco con threshold bajo.
        from app import job_health, metrics

        fresh = job_health.JobHealthTracker(threshold=2)
        monkeypatch.setattr(job_health, "_tracker", fresh)
        # `metrics.track_job` llama a `get_tracker()` cada vez — apunta al
        # nuevo tracker.
        monkeypatch.setattr(metrics, "get_tracker", lambda: fresh)

        sent: list[str] = []

        async def fake_send_admin_alert(message: str) -> bool:
            sent.append(message)
            return True

        monkeypatch.setattr(metrics, "send_admin_alert", fake_send_admin_alert)
        # El gauge global no se aísla entre tests; reseteamos a 0 antes.
        for label in ("flaky_job", "happy_job"):
            JOB_CONSECUTIVE_FAILURES.labels(job_name=label).set(0)
        return sent

    async def test_alerts_when_threshold_crossed(
        self, reset_tracker_and_capture_alerts
    ):
        sent = reset_tracker_and_capture_alerts

        # 1er fallo: no alerta.
        with pytest.raises(RuntimeError):
            async with track_job("flaky_job"):
                raise RuntimeError("boom")
        assert sent == []

        # 2do fallo: cruza umbral 2 → alerta.
        with pytest.raises(RuntimeError):
            async with track_job("flaky_job"):
                raise RuntimeError("boom")
        assert len(sent) == 1
        assert "flaky_job" in sent[0]
        assert "2 veces" in sent[0]

        # 3er fallo: ya había alerta activa, NO repite.
        with pytest.raises(RuntimeError):
            async with track_job("flaky_job"):
                raise RuntimeError("boom")
        assert len(sent) == 1

    async def test_recovery_alert_on_first_ok_after_incident(
        self, reset_tracker_and_capture_alerts
    ):
        sent = reset_tracker_and_capture_alerts

        for _ in range(2):
            with pytest.raises(RuntimeError):
                async with track_job("flaky_job"):
                    raise RuntimeError("boom")
        assert len(sent) == 1  # alerta de incidente

        # Job vuelve a OK: recovery alert.
        async with track_job("flaky_job"):
            pass
        assert len(sent) == 2
        assert "recuperado" in sent[1].lower()

        # Próximas ok no spamean.
        async with track_job("flaky_job"):
            pass
        assert len(sent) == 2

    async def test_happy_job_never_alerts(
        self, reset_tracker_and_capture_alerts
    ):
        sent = reset_tracker_and_capture_alerts
        for _ in range(5):
            async with track_job("happy_job"):
                pass
        assert sent == []
