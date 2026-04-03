"""Jobs periódicos para el scheduler."""

import logging

from app.adapters.normalizer import TeamNormalizer
from app.adapters.odds_api import OddsAPIAdapter
from app.config import settings
from app.database import async_session
from app.services.odds_service import OddsIngestionService
from app.services.opportunity_service import OpportunityDetectionService

logger = logging.getLogger(__name__)


async def fetch_odds_job():
    """Job: obtiene cuotas de fuentes externas y las guarda en DB."""
    if not settings.ODDS_API_KEY:
        logger.warning("ODDS_API_KEY not configured, skipping fetch")
        return

    adapter = OddsAPIAdapter()
    service = OddsIngestionService(adapter, TeamNormalizer())

    try:
        async with async_session() as db:
            counts = await service.ingest_odds(
                db,
                sport_key="football",
                regions=["eu", "uk"],
                markets=["h2h"],
            )
            logger.info(
                "Fetch complete: %d events, %d odds saved, %d errors",
                counts["events"], counts["odds_saved"], counts["errors"],
            )
    except Exception as e:
        logger.error(f"Fetch odds job failed: {e}")
    finally:
        await adapter.close()


async def detect_value_job():
    """Job: detecta value bets y envía notificaciones."""
    from app.notifications.service import NotificationService

    service = OpportunityDetectionService(min_value=0.03, min_bookmakers=3)
    notification_service = NotificationService()

    try:
        async with async_session() as db:
            counts, new_opportunities = await service.detect_all(db)
            logger.info(
                "Detection complete: %d opportunities found, %d expired, %d errors",
                counts["opportunities_found"],
                counts.get("expired", 0),
                counts["errors"],
            )

            # Send notifications for new opportunities
            if new_opportunities:
                notif_counts = await notification_service.notify_new_opportunities(
                    db, new_opportunities
                )
                logger.info(
                    "Notifications: %d sent, %d failed",
                    notif_counts["sent"],
                    notif_counts["failed"],
                )
    except Exception as e:
        logger.error(f"Detect value job failed: {e}")


async def cleanup_job():
    """Job: limpieza de datos expirados."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models.match import Match

    try:
        async with async_session() as db:
            now = datetime.now(timezone.utc)

            # Mark past matches as completed (if no score, just mark them)
            result = await db.execute(
                select(Match).where(
                    Match.status == "scheduled",
                    Match.commence_time < now,
                )
            )
            completed = 0
            for match in result.scalars().all():
                match.status = "completed"
                completed += 1

            await db.commit()
            logger.info("Cleanup: %d matches marked completed", completed)
    except Exception as e:
        logger.error(f"Cleanup job failed: {e}")
