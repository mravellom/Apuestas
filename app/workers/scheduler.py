"""Configuración de APScheduler con jobs periódicos."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.workers.jobs import (
    capture_closing_lines_job,
    cleanup_job,
    detect_arbitrage_job,
    detect_value_job,
    fetch_odds_job,
    fetch_scores_job,
)

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def configure_scheduler():
    """Configura los jobs del scheduler."""

    # Fetch odds — intervalo configurable (default 15 min, seguro para free tier)
    scheduler.add_job(
        fetch_odds_job,
        "interval",
        seconds=settings.SCHEDULER_FETCH_ODDS_SECONDS,
        id="fetch_odds",
        name="Fetch odds from external sources",
        replace_existing=True,
        max_instances=1,
    )

    # Detect value bets tras el fetch (solo si está habilitado en settings)
    if settings.VALUE_DETECTION_ENABLED:
        scheduler.add_job(
            detect_value_job,
            "interval",
            seconds=settings.SCHEDULER_DETECT_SECONDS,
            id="detect_value",
            name="Detect value betting opportunities",
            replace_existing=True,
            max_instances=1,
        )
    else:
        logger.info("Value detection disabled via VALUE_DETECTION_ENABLED=false")

    # Detect arbitrage (surebets)
    scheduler.add_job(
        detect_arbitrage_job,
        "interval",
        seconds=settings.SCHEDULER_DETECT_SECONDS,
        id="detect_arbitrage",
        name="Detect arbitrage opportunities",
        replace_existing=True,
        max_instances=1,
    )

    # Capture closing lines cada minuto (partidos a <=5 min del kickoff)
    scheduler.add_job(
        capture_closing_lines_job,
        "interval",
        minutes=1,
        id="capture_closing_lines",
        name="Capture closing lines",
        replace_existing=True,
        max_instances=1,
    )

    # Fetch scores and settle paper bets
    scheduler.add_job(
        fetch_scores_job,
        "interval",
        seconds=settings.SCHEDULER_SCORES_SECONDS,
        id="fetch_scores",
        name="Fetch match scores and settle paper bets",
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
    if scheduler.running:
        logger.warning("Scheduler already running, skipping start")
        return
    configure_scheduler()
    scheduler.start()
    logger.info("Scheduler started")


def shutdown_scheduler():
    """Detiene el scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
