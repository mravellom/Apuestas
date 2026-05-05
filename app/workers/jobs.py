"""Jobs periódicos para el scheduler."""

import logging
from datetime import datetime, timezone

from app.adapters.normalizer import TeamNormalizer
from app.adapters.odds_api import OddsAPIAdapter
from app.config import settings
from app.database import async_session
from app.metrics import tracked_job
from app.services.odds_service import OddsIngestionService
from app.services.opportunity_service import OpportunityDetectionService

logger = logging.getLogger(__name__)


async def _get_last_successful_fetch_at(db) -> datetime | None:
    """Última vez que fetch_odds_job persistió un ApiUsageLog (señal de éxito).

    Reemplaza al `_last_fetch_at` en memoria: persiste cross-restart y solo
    avanza tras un fetch que efectivamente llamó al adapter y commiteó. Si el
    job explota antes del primer commit de usage, no marca falsa actividad —
    el siguiente tick reintenta correctamente.
    """
    from sqlalchemy import select as _select
    from app.models.api_usage import ApiUsageLog as _Log

    return (
        await db.execute(
            _select(_Log.captured_at)
            .where(_Log.source == "odds_api")
            .order_by(_Log.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


# Regiones y mercados por deporte — hardcoded porque no cambian por liga.
# Si un deporte no está listado aquí, las ligas de ese deporte no se fetchearán
# aunque tengan detection_enabled=True (salvaguarda contra fetches accidentales).
SPORT_FETCH_SETTINGS: dict[str, dict[str, list[str]]] = {
    "football": {
        # "uk" quitado: libros UK no ejecutables desde Chile y no aportan en
        # ligas Latam (Brasileirão, Argentina, etc.). Restaurar si se activa
        # una liga europea con acceso confirmado desde Chile.
        "regions": ["eu", "us", "us2"],
        "markets": ["h2h"],
    },
    "baseball": {
        "regions": ["us", "us2", "eu"],
        "markets": ["h2h", "totals"],
    },
    "basketball": {
        "regions": ["us", "us2", "eu"],
        "markets": ["h2h", "totals"],
    },
    "americanfootball": {
        "regions": ["us", "us2", "eu"],
        "markets": ["h2h", "spreads", "totals"],
    },
    "icehockey": {
        "regions": ["us", "us2", "eu"],
        "markets": ["h2h", "totals"],
    },
    "mma": {
        # MMA en Odds API es 2-way h2h puro. US offshore + Pinnacle (vía SportMarket)
        # son la cobertura ejecutable desde Chile.
        "regions": ["us", "us2", "eu"],
        "markets": ["h2h"],
    },
    "boxing": {
        "regions": ["us", "us2", "eu"],
        "markets": ["h2h"],
    },
    "tennis": {
        "regions": ["eu", "us", "us2"],
        "markets": ["h2h"],
    },
}


def _in_quiet_window(hour_utc: int, start: int, end: int) -> bool:
    """True si `hour_utc` cae en la franja [start, end) con wraparound."""
    if start == end:
        return False
    if start < end:
        return start <= hour_utc < end
    return hour_utc >= start or hour_utc < end


def _required_interval_seconds(proximity_hours: float | None) -> int:
    """Cadencia objetivo según horas hasta el próximo partido activo.

    None = sin partidos próximos en el horizonte → cadencia FAR.
    """
    if proximity_hours is None:
        return settings.FETCH_ODDS_INTERVAL_FAR_SECONDS
    if proximity_hours <= settings.FETCH_ODDS_NEAR_KICKOFF_HOURS:
        return settings.FETCH_ODDS_INTERVAL_NEAR_SECONDS
    if proximity_hours <= settings.FETCH_ODDS_MID_KICKOFF_HOURS:
        return settings.FETCH_ODDS_INTERVAL_MID_SECONDS
    return settings.FETCH_ODDS_INTERVAL_FAR_SECONDS


async def _next_match_proximity_hours(db) -> float | None:
    """Horas hasta el próximo `commence_time` con detección activa.

    Retorna None si no hay partidos en el horizonte ARB_MAX_HOURS_TO_KICKOFF.
    """
    from datetime import timedelta

    from sqlalchemy import func, select

    from app.models.match import Match
    from app.models.sport import League, Season

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    horizon = now + timedelta(hours=settings.ARB_MAX_HOURS_TO_KICKOFF)
    next_commence = (
        await db.execute(
            select(func.min(Match.commence_time))
            .join(Season, Season.id == Match.season_id)
            .join(League, League.id == Season.league_id)
            .where(
                League.detection_enabled.is_(True),
                Match.commence_time > now,
                Match.commence_time <= horizon,
            )
        )
    ).scalar()
    if next_commence is None:
        return None
    return (next_commence - now).total_seconds() / 3600


@tracked_job("fetch_odds")
async def fetch_odds_job():
    """
    Job: obtiene cuotas solo de las ligas con detection_enabled=True, agrupadas
    por sport. Esto hace que el toggle admin controle fetch + detect sin redeploy.
    """
    if not settings.ODDS_API_KEY:
        logger.warning("ODDS_API_KEY not configured, skipping fetch")
        return

    hour_utc = datetime.now(timezone.utc).hour
    if _in_quiet_window(
        hour_utc,
        settings.FETCH_ODDS_QUIET_START_UTC,
        settings.FETCH_ODDS_QUIET_END_UTC,
    ):
        logger.info(
            "Fetch skipped: hour %d UTC in quiet window [%d, %d)",
            hour_utc,
            settings.FETCH_ODDS_QUIET_START_UTC,
            settings.FETCH_ODDS_QUIET_END_UTC,
        )
        return

    from sqlalchemy import select
    from app.models.sport import League, Sport

    # Smart polling: el scheduler tickea cada NEAR_SECONDS, pero el job decide
    # si fetchea según proximidad del próximo partido. El histórico 14d muestra
    # que ~70% de arbs ≥3% profit nacen en la ventana 1-3h pre-kickoff.
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    async with async_session() as proximity_db:
        proximity_hours = await _next_match_proximity_hours(proximity_db)
        last_fetch_at = await _get_last_successful_fetch_at(proximity_db)
    required_interval = _required_interval_seconds(proximity_hours)
    if last_fetch_at is not None:
        elapsed = (now_utc - last_fetch_at).total_seconds()
        if elapsed < required_interval:
            logger.info(
                "Fetch throttled: next match in %s, required %ds, elapsed %ds",
                f"{proximity_hours:.1f}h" if proximity_hours is not None else "n/a",
                required_interval,
                int(elapsed),
            )
            return

    adapter = OddsAPIAdapter()
    service = OddsIngestionService(adapter, TeamNormalizer())

    try:
        async with async_session() as db:
            active = (
                await db.execute(
                    select(Sport.key, League.key)
                    .join(League, League.sport_id == Sport.id)
                    .where(League.detection_enabled.is_(True))
                )
            ).all()

            if not active:
                logger.info("No leagues with detection_enabled=True — nothing to fetch")
                return

            # Agrupa ligas por sport para enviar una request por (sport, regions, markets).
            leagues_by_sport: dict[str, list[str]] = {}
            for sport_key, league_key in active:
                leagues_by_sport.setdefault(sport_key, []).append(league_key)

            # Quota guard: si el último snapshot persistido dice 0 créditos,
            # no tiene sentido pegar al endpoint. Igual chequeamos por sport
            # post-fetch para cortar antes de gastar el resto en el resto.
            from app.models.api_usage import ApiUsageLog
            from app.admin_alerter import send_admin_alert

            last_known = (
                await db.execute(
                    select(ApiUsageLog.requests_remaining)
                    .where(ApiUsageLog.source == "odds_api")
                    .order_by(ApiUsageLog.captured_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last_known is not None and last_known <= 0:
                logger.warning(
                    "Odds API quota exhausted (last_known=%d); skipping fetch", last_known
                )
                await send_admin_alert(
                    f"Odds API quota agotada (last_known={last_known}). "
                    "Fetches pausados hasta reset mensual o upgrade del plan."
                )
                return

            total = {"events": 0, "odds_saved": 0, "errors": 0}
            low_quota_alerted = False
            for sport_key, league_keys in leagues_by_sport.items():
                cfg = SPORT_FETCH_SETTINGS.get(sport_key)
                if cfg is None:
                    logger.warning(
                        "Sport %s activo en %d liga(s) pero sin config de fetch; skip",
                        sport_key, len(league_keys),
                    )
                    continue
                # Chequeo previo por sport: si la última lectura dice 0, no
                # pegues al endpoint (evita 401/403 por quota agotada).
                pre_usage = getattr(adapter, "last_usage", None)
                if (
                    pre_usage is not None
                    and pre_usage.requests_remaining is not None
                    and pre_usage.requests_remaining <= 0
                ):
                    logger.warning(
                        "Odds API quota hit 0 mid-run; aborting remaining sports"
                    )
                    await send_admin_alert(
                        "Odds API quota agotada durante fetch_odds_job. "
                        f"Sports restantes saltados: {len(leagues_by_sport)}"
                    )
                    break
                try:
                    c = await service.ingest_odds(
                        db,
                        sport_key=sport_key,
                        league_keys=league_keys,
                        regions=cfg["regions"],
                        markets=cfg["markets"],
                    )
                    for k in total:
                        total[k] += c.get(k, 0)
                except Exception:
                    # Una falla por sport no debe matar el job: persistencia
                    # parcial OK, el siguiente tick reintenta lo no completado.
                    logger.exception(
                        "Sport %s fetch failed; continuing with remaining sports",
                        sport_key,
                    )
                    total["errors"] += 1
                usage = getattr(adapter, "last_usage", None)
                if usage is not None:
                    db.add(ApiUsageLog(
                        source=adapter.SOURCE,
                        sport_key=sport_key,
                        endpoint=usage.endpoint,
                        requests_remaining=usage.requests_remaining,
                        requests_used=usage.requests_used,
                    ))
                    await db.commit()
                    # Alerta una sola vez por run cuando cruzamos el umbral.
                    rem = usage.requests_remaining
                    if (
                        rem is not None
                        and 0 < rem < settings.ODDS_API_LOW_QUOTA_THRESHOLD
                        and not low_quota_alerted
                    ):
                        logger.warning(
                            "Odds API low quota: %d remaining (threshold %d)",
                            rem, settings.ODDS_API_LOW_QUOTA_THRESHOLD,
                        )
                        await send_admin_alert(
                            f"Odds API quota baja: {rem} requests restantes "
                            f"(threshold {settings.ODDS_API_LOW_QUOTA_THRESHOLD})."
                        )
                        low_quota_alerted = True
                        low_quota_alerted = True
            counts = total
            logger.info(
                "Fetch complete: %d events, %d odds saved, %d errors",
                counts["events"], counts["odds_saved"], counts["errors"],
            )
    except Exception as e:
        logger.exception("Fetch odds job failed")
    finally:
        await adapter.close()


@tracked_job("detect_value")
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
        logger.exception("Detect value job failed")


@tracked_job("detect_arbitrage")
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
        min_profit_pct=settings.ARB_MIN_PROFIT_PCT,
        min_bookmakers=settings.ARB_MIN_BOOKMAKERS,
        max_odds_age_minutes=settings.ARB_MAX_ODDS_AGE_MINUTES,
        max_minutes_to_kickoff=settings.ARB_MAX_HOURS_TO_KICKOFF * 60,
    )

    try:
        async with async_session() as db:
            counts, new_arbs = await service.detect_all(db)
            killed = await service.sweep_dead_arbs(db)
            logger.info(
                "Arbitrage scan: %d arbs found, %d expired, %d killed, %d errors",
                counts["arbs_found"],
                counts.get("expired", 0),
                killed,
                counts["errors"],
            )

            if not new_arbs:
                return

            # Get alert configs for telegram + user's preferred currency for format
            from sqlalchemy import select
            from app.models.user import UserConfig
            alerts = (
                await db.execute(
                    select(AlertConfig).where(AlertConfig.active.is_(True))
                )
            ).scalars().all()

            if not alerts:
                return

            # Map user_id → default_currency para formatear notifs.
            user_ids = list({a.user_id for a in alerts})
            cfgs = (
                await db.execute(
                    select(UserConfig).where(UserConfig.user_id.in_(user_ids))
                )
            ).scalars().all()
            currency_by_user = {c.user_id: c.default_currency for c in cfgs}

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
                            currency = currency_by_user.get(alert.user_id, "USD")
                            ok = await notifier.send(alert.destination, payload, currency)
                            if ok:
                                sent += 1
                            else:
                                failed += 1
                        except Exception as e:
                            logger.exception("Arb notification error")
                            failed += 1
            finally:
                await notifier.close()

            logger.info("Arb notifications: %d sent, %d failed", sent, failed)

    except Exception as e:
        logger.exception("Detect arbitrage job failed")


@tracked_job("capture_closing_lines")
async def capture_closing_lines_job():
    """Job: congela la última cuota disponible como closing line para partidos próximos a empezar."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select, update
    from sqlalchemy.dialects.postgresql import insert

    from app.models.market import ClosingLine, Market, Odds, Outcome
    from app.models.match import Match
    from app.models.paper import PaperBet

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
            clv_filled = 0
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

                        # Backfill CLV en PaperBets del mismo (outcome, bookmaker).
                        # Solo rellenamos closing_odds NULL — si ya existe lo respetamos
                        # (re-runs del job no deben sobrescribir un cierre anterior).
                        result = await db.execute(
                            update(PaperBet)
                            .where(
                                PaperBet.outcome_id == outcome.id,
                                PaperBet.bookmaker_id == bm_id,
                                PaperBet.closing_odds.is_(None),
                            )
                            .values(closing_odds=price)
                        )
                        clv_filled += result.rowcount or 0

            await db.commit()
            logger.info(
                "Closing lines captured: %d rows across %d matches; CLV backfilled on %d paper bets",
                captured, len(matches), clv_filled,
            )
    except Exception as e:
        logger.exception("Capture closing lines job failed")


@tracked_job("fetch_scores")
async def fetch_scores_job():
    """Job: obtiene resultados de partidos recientes y liquida paper bets.

    The Odds API `/sports/{sport}/scores?daysFrom=3` es gratis para partidos
    completados en los últimos 3 días. Marca matches como completed con scores
    y dispara settlement de paper bets pendientes.
    """
    if not settings.ODDS_API_KEY:
        return

    import httpx
    from sqlalchemy import select
    from app.models.match import Match
    from app.models.paper import PaperBet
    from app.models.sport import League, Season
    from app.services.paper_trading_service import PaperTradingService

    # Ligas a consultar = detection_enabled UNION ligas con paper bets pendientes.
    # El segundo término evita orfandar bets sin liquidar cuando una liga se
    # desactiva con apuestas vivas adentro.
    async with async_session() as db:
        enabled_keys = (await db.execute(
            select(League.key).where(League.detection_enabled.is_(True))
        )).scalars().all()
        pending_keys = (await db.execute(
            select(League.key)
            .join(Season, Season.league_id == League.id)
            .join(Match, Match.season_id == Season.id)
            .join(PaperBet, PaperBet.match_id == Match.id)
            .where(PaperBet.result == "pending")
            .distinct()
        )).scalars().all()
        leagues = sorted(set(enabled_keys) | set(pending_keys))

    if not leagues:
        logger.info("Scores: no active or pending-bet leagues; skipping fetch")
        return

    updated = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        for league in leagues:
            try:
                r = await client.get(
                    f"{settings.ODDS_API_BASE_URL}/sports/{league}/scores",
                    params={"apiKey": settings.ODDS_API_KEY, "daysFrom": 3},
                )
                if r.status_code != 200:
                    continue
                events = r.json()
            except Exception as e:
                logger.exception("Scores fetch error for %s", league)
                continue

            async with async_session() as db:
                for evt in events:
                    if not evt.get("completed") or not evt.get("scores"):
                        continue
                    match = (
                        await db.execute(select(Match).where(Match.external_id == evt.get("id")))
                    ).scalar_one_or_none()
                    if not match:
                        continue
                    home_score = next((int(s["score"]) for s in evt["scores"] if s["name"] == evt["home_team"]), None)
                    away_score = next((int(s["score"]) for s in evt["scores"] if s["name"] == evt["away_team"]), None)
                    if home_score is None or away_score is None:
                        continue
                    if match.home_score != home_score or match.away_score != away_score or match.status != "completed":
                        match.home_score = home_score
                        match.away_score = away_score
                        match.status = "completed"
                        updated += 1
                await db.commit()

    # Settle any paper bets whose matches are now completed with scores
    async with async_session() as db:
        paper = PaperTradingService()
        settle_result = await paper.settle_all_completed(db)
        logger.info(
            "Scores: %d match scores updated; settled %d paper bets across %d matches",
            updated, settle_result["settled"], settle_result["matches"],
        )


@tracked_job("cleanup")
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
        logger.exception("Cleanup job failed")
