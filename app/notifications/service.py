"""Servicio de notificaciones: orquesta el envío según config del usuario."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import AlertConfig
from app.models.bookmaker import Bookmaker
from app.models.market import Market, MarketType, Outcome
from app.models.match import Match
from app.models.opportunity import Opportunity
from app.models.team import Team
from app.notifications.base import Notifier, NotificationPayload
from app.notifications.email_notifier import EmailNotifier
from app.notifications.telegram_notifier import TelegramNotifier
from app.notifications.webhook_notifier import WebhookNotifier

logger = logging.getLogger(__name__)

_NOTIFIERS: dict[str, Notifier] = {}


def get_notifier(channel: str) -> Notifier:
    """Factory de notifiers con cache (singleton por canal)."""
    if channel not in _NOTIFIERS:
        if channel == "telegram":
            _NOTIFIERS[channel] = TelegramNotifier()
        elif channel == "webhook":
            _NOTIFIERS[channel] = WebhookNotifier()
        elif channel == "email":
            _NOTIFIERS[channel] = EmailNotifier()
        else:
            raise ValueError(f"Unknown notification channel: {channel}")
    return _NOTIFIERS[channel]


# Alias retrocompatible — código legado todavía importa _get_notifier.
_get_notifier = get_notifier


def build_test_payload() -> NotificationPayload:
    """
    Payload fijo etiquetado como TEST. Usa valores realistas para que el
    formato del mensaje en cada canal se pueda validar de un vistazo, pero
    los nombres del partido dejan claro que no es real.
    """
    return NotificationPayload(
        match_home="[TEST] Home",
        match_away="[TEST] Away",
        commence_time="2099-01-01 00:00 UTC",
        market_type="h2h",
        outcome_name="Home",
        bookmaker_name="TestBook",
        odds_price=2.10,
        value_pct=0.05,
        consensus_prob=0.50,
        kelly_stake_pct=0.0125,
    )


class NotificationService:
    async def notify_new_opportunities(
        self, db: AsyncSession, opportunities: list[Opportunity]
    ) -> dict[str, int]:
        """
        Envía notificaciones para nuevas oportunidades a usuarios con alertas configuradas.

        Returns:
            {"sent": N, "failed": N}
        """
        counts = {"sent": 0, "failed": 0}

        if not opportunities:
            return counts

        # Get all active alert configs
        result = await db.execute(
            select(AlertConfig).where(AlertConfig.active.is_(True))
        )
        alerts = result.scalars().all()

        if not alerts:
            return counts

        for opp in opportunities:
            payload = await self._build_payload(db, opp)
            if not payload:
                continue

            for alert in alerts:
                # Filter by min_value
                if float(opp.value_pct) < float(alert.min_value_pct):
                    continue

                # Filter by sport (if configured)
                if alert.sports_filter:
                    match_sport = await self._get_opportunity_sport(db, opp)
                    if match_sport and match_sport not in alert.sports_filter:
                        continue

                try:
                    notifier = get_notifier(alert.channel)
                    success = await notifier.send(alert.destination, payload)
                    if success:
                        counts["sent"] += 1
                    else:
                        counts["failed"] += 1
                except Exception:
                    logger.exception("Notification error for alert %d", alert.id)
                    counts["failed"] += 1

        return counts

    async def _build_payload(
        self, db: AsyncSession, opp: Opportunity
    ) -> NotificationPayload | None:
        """Construye el payload de notificación desde una oportunidad."""
        outcome = await db.get(Outcome, opp.outcome_id)
        if not outcome:
            return None

        market = await db.get(Market, outcome.market_id)
        market_type = await db.get(MarketType, market.market_type_id)
        match = await db.get(Match, market.match_id)
        home_team = await db.get(Team, match.home_team_id)
        away_team = await db.get(Team, match.away_team_id)
        bookmaker = await db.get(Bookmaker, opp.bookmaker_id)

        return NotificationPayload(
            match_home=home_team.canonical_name,
            match_away=away_team.canonical_name,
            commence_time=match.commence_time.strftime("%Y-%m-%d %H:%M UTC"),
            market_type=market_type.key,
            outcome_name=outcome.name,
            bookmaker_name=bookmaker.name,
            odds_price=float(opp.odds_price),
            value_pct=float(opp.value_pct),
            consensus_prob=float(opp.consensus_prob),
            kelly_stake_pct=float(opp.kelly_stake_pct) if opp.kelly_stake_pct else None,
        )

    async def _get_opportunity_sport(
        self, db: AsyncSession, opp: Opportunity
    ) -> str | None:
        """Obtiene el sport_key de una oportunidad."""
        from app.models.sport import League, Season, Sport

        outcome = await db.get(Outcome, opp.outcome_id)
        if not outcome:
            return None
        market = await db.get(Market, outcome.market_id)
        match = await db.get(Match, market.match_id)
        season = await db.get(Season, match.season_id)
        league = await db.get(League, season.league_id)
        sport = await db.get(Sport, league.sport_id)
        return sport.key if sport else None
