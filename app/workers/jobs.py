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
                league_keys=[
                    "soccer_chile_campeonato",
                    "soccer_brazil_campeonato",
                    "soccer_italy_serie_b",
                ],
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

    service = OpportunityDetectionService(
        min_value=settings.VALUE_MIN_EV,
        min_bookmakers=3,
        reference_bookmaker=settings.VALUE_REFERENCE_BOOKMAKER or None,
    )
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


async def detect_arbitrage_job():
    """Job: detecta oportunidades de arbitraje (surebets) y notifica."""
    from app.models.match import Match
    from app.models.market import Market, MarketType
    from app.models.team import Team
    from app.notifications.base import ArbitragePayload
    from app.notifications.telegram_notifier import TelegramNotifier
    from app.models.alert import AlertConfig

    from app.services.arbitrage_service import ArbitrageDetectionService

    service = ArbitrageDetectionService(
        min_profit_pct=0.5,
        min_bookmakers=settings.ARB_MIN_BOOKMAKERS,
    )

    try:
        async with async_session() as db:
            counts, new_arbs = await service.detect_all(db)
            logger.info(
                "Arbitrage scan: %d arbs found, %d expired, %d errors",
                counts["arbs_found"],
                counts.get("expired", 0),
                counts["errors"],
            )

            if not new_arbs:
                return

            # Get alert configs for telegram
            from sqlalchemy import select
            alerts = (
                await db.execute(
                    select(AlertConfig).where(AlertConfig.active.is_(True))
                )
            ).scalars().all()

            if not alerts:
                return

            notifier = TelegramNotifier()
            sent, failed = 0, 0

            try:
                for arb in new_arbs:
                    match = await db.get(Match, arb.match_id)
                    market = await db.get(Market, arb.market_id)
                    market_type = await db.get(MarketType, market.market_type_id)
                    home = await db.get(Team, match.home_team_id)
                    away = await db.get(Team, match.away_team_id)

                    payload = ArbitragePayload(
                        match_home=home.canonical_name,
                        match_away=away.canonical_name,
                        commence_time=match.commence_time.strftime("%Y-%m-%d %H:%M UTC"),
                        market_type=market_type.key,
                        profit_pct=float(arb.profit_pct),
                        total_implied=float(arb.total_implied),
                        legs=arb.legs,
                    )

                    for alert in alerts:
                        try:
                            ok = await notifier.send(alert.destination, payload)
                            if ok:
                                sent += 1
                            else:
                                failed += 1
                        except Exception as e:
                            logger.error("Arb notification error: %s", e)
                            failed += 1
            finally:
                await notifier.close()

            logger.info("Arb notifications: %d sent, %d failed", sent, failed)

    except Exception as e:
        logger.error("Detect arbitrage job failed: %s", e)


async def capture_closing_lines_job():
    """Job: congela la última cuota disponible como closing line para partidos próximos a empezar."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert

    from app.models.market import ClosingLine, Market, Odds, Outcome
    from app.models.match import Match

    try:
        async with async_session() as db:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            window_end = now + timedelta(minutes=5)

            matches = (
                await db.execute(
                    select(Match).where(
                        Match.status == "scheduled",
                        Match.commence_time > now,
                        Match.commence_time <= window_end,
                    )
                )
            ).scalars().all()

            captured = 0
            for match in matches:
                outcomes = (
                    await db.execute(
                        select(Outcome)
                        .join(Market, Market.id == Outcome.market_id)
                        .where(Market.match_id == match.id)
                    )
                ).scalars().all()

                for outcome in outcomes:
                    rows = (
                        await db.execute(
                            select(
                                Odds.bookmaker_id,
                                Odds.price,
                                Odds.captured_at,
                            )
                            .where(Odds.outcome_id == outcome.id)
                            .order_by(Odds.bookmaker_id, Odds.captured_at.desc())
                            .distinct(Odds.bookmaker_id)
                        )
                    ).all()

                    for bm_id, price, captured_at in rows:
                        stmt = (
                            insert(ClosingLine)
                            .values(
                                outcome_id=outcome.id,
                                bookmaker_id=bm_id,
                                price=price,
                                captured_at=captured_at,
                            )
                            .on_conflict_do_nothing(
                                constraint="uq_closing_outcome_bm"
                            )
                        )
                        await db.execute(stmt)
                        captured += 1

            await db.commit()
            logger.info(
                "Closing lines captured: %d rows across %d matches",
                captured, len(matches),
            )
    except Exception as e:
        logger.error(f"Capture closing lines job failed: {e}")


async def cleanup_job():
    """Job: limpieza de datos expirados."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models.match import Match

    try:
        async with async_session() as db:
            now = datetime.now(timezone.utc).replace(tzinfo=None)

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
