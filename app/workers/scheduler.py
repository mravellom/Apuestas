"""Configuración de APScheduler con jobs periódicos."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.workers.jobs import fetch_odds_job, detect_value_job, cleanup_job

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def configure_scheduler():
    """Configura los jobs del scheduler."""

    # Fetch odds cada 5 minutos
    scheduler.add_job(
        fetch_odds_job,
        "interval",
        minutes=5,
        id="fetch_odds",
        name="Fetch odds from external sources",
        replace_existing=True,
        max_instances=1,
    )

    # Detect value bets cada 5 minutos (1 min después del fetch)
    scheduler.add_job(
        detect_value_job,
        "interval",
        minutes=5,
        id="detect_value",
        name="Detect value betting opportunities",
        replace_existing=True,
        max_instances=1,
    )

    # Cleanup de oportunidades expiradas cada hora
    scheduler.add_job(
        cleanup_job,
        "interval",
        hours=1,
        id="cleanup",
        name="Cleanup expired opportunities",
        replace_existing=True,
        max_instances=1,
    )

    logger.info("Scheduler configured with %d jobs", len(scheduler.get_jobs()))


def start_scheduler():
    """Inicia el scheduler."""
    configure_scheduler()
    scheduler.start()
    logger.info("Scheduler started")


def shutdown_scheduler():
    """Detiene el scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
