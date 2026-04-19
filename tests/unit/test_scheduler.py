"""Tests para workers/scheduler.py (configuración, start idempotente, shutdown)."""

import pytest

from app.workers import scheduler as scheduler_module


@pytest.fixture(autouse=True)
def _clean_scheduler():
    """Cada test empieza y termina con scheduler parado y vacío."""
    try:
        if scheduler_module.scheduler.running:
            scheduler_module.scheduler.shutdown(wait=False)
    except Exception:
        pass
    scheduler_module.scheduler.remove_all_jobs()
    yield
    try:
        if scheduler_module.scheduler.running:
            scheduler_module.scheduler.shutdown(wait=False)
    except Exception:
        pass
    scheduler_module.scheduler.remove_all_jobs()


EXPECTED_JOB_IDS = {
    "fetch_odds",
    "detect_value",
    "detect_arbitrage",
    "capture_closing_lines",
    "fetch_scores",
    "cleanup",
}


class TestConfigureScheduler:
    def test_registers_all_expected_jobs(self):
        scheduler_module.configure_scheduler()
        job_ids = {job.id for job in scheduler_module.scheduler.get_jobs()}
        assert EXPECTED_JOB_IDS <= job_ids
        assert len(scheduler_module.scheduler.get_jobs()) == len(EXPECTED_JOB_IDS)

    def test_intervals_match_design(self):
        from app.config import settings
        scheduler_module.configure_scheduler()

        intervals = {
            job.id: int(job.trigger.interval.total_seconds())
            for job in scheduler_module.scheduler.get_jobs()
        }
        assert intervals["fetch_odds"] == settings.SCHEDULER_FETCH_ODDS_SECONDS
        assert intervals["detect_value"] == settings.SCHEDULER_DETECT_SECONDS
        assert intervals["detect_arbitrage"] == settings.SCHEDULER_DETECT_SECONDS
        assert intervals["capture_closing_lines"] == 60
        assert intervals["fetch_scores"] == settings.SCHEDULER_SCORES_SECONDS
        assert intervals["cleanup"] == 60 * 60

    def test_max_instances_is_one(self):
        """All jobs must have max_instances=1 to avoid overlapping runs."""
        scheduler_module.configure_scheduler()
        for job in scheduler_module.scheduler.get_jobs():
            assert job.max_instances == 1


class TestStartScheduler:
    async def test_start_marks_running(self):
        """start_scheduler() puts the AsyncIOScheduler in running state."""
        assert scheduler_module.scheduler.running is False

        scheduler_module.start_scheduler()
        try:
            assert scheduler_module.scheduler.running is True
            # And registers the expected jobs as part of startup
            job_ids = {job.id for job in scheduler_module.scheduler.get_jobs()}
            assert EXPECTED_JOB_IDS <= job_ids
        finally:
            scheduler_module.shutdown_scheduler()

    async def test_start_is_idempotent(self, caplog):
        """A second start on a running scheduler should warn and be a no-op."""
        import logging

        scheduler_module.start_scheduler()
        try:
            with caplog.at_level(logging.WARNING, logger="app.workers.scheduler"):
                scheduler_module.start_scheduler()

            assert any(
                "already running" in rec.message.lower()
                for rec in caplog.records
            )
            assert scheduler_module.scheduler.running is True
        finally:
            scheduler_module.shutdown_scheduler()


class TestShutdownScheduler:
    async def test_shutdown_stops_running_scheduler(self):
        import asyncio

        scheduler_module.start_scheduler()
        assert scheduler_module.scheduler.running is True

        scheduler_module.shutdown_scheduler()
        # AsyncIOScheduler.shutdown(wait=False) schedules state transition;
        # yield to the event loop so the stopped state becomes visible.
        await asyncio.sleep(0)
        assert scheduler_module.scheduler.running is False
