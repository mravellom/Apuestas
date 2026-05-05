"""Servicio de detección de oportunidades: consensus → detect → save."""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.steam import detect_steam_signal
from app.core.value_detector import (
    ValueBet,
    detect_value_bets,
    detect_value_bets_vs_reference,
)
from app.models.bookmaker import Bookmaker
from app.models.market import Market, Odds, Outcome
from app.models.match import Match
from app.models.opportunity import Opportunity
from app.models.sport import League, Season
from app.services.paper_trading_service import PaperTradingService, PendingValueBet

logger = logging.getLogger(__name__)


class OpportunityDetectionService:
    def __init__(
        self,
        min_value: float = 0.05,
        min_bookmakers: int = 5,
        min_minutes_to_kickoff: int = 15,
        max_minutes_to_kickoff: int = 10080,  # 7 days — tighten to 48h for real betting
        reference_bookmaker: str | None = None,
        max_odds_age_minutes: int = 30,
    ):
        self.min_value = min_value
        self.min_bookmakers = min_bookmakers
        self.min_minutes_to_kickoff = min_minutes_to_kickoff
        self.max_minutes_to_kickoff = max_minutes_to_kickoff
        self.reference_bookmaker = reference_bookmaker
        # Cuotas mas viejas que esto se descartan al calcular consenso. Sin
        # esto, un libro que dejo de actualizar (mercado suspendido sin que el
        # feed lo marque) sigue contando hacia el "fair price" y emite value
        # bets fantasma a precios que ya no existen.
        self.max_odds_age_minutes = max_odds_age_minutes
        self.paper = PaperTradingService()

    async def detect_all(
        self, db: AsyncSession
    ) -> tuple[dict[str, int], list[Opportunity]]:
        """
        Detecta value bets en todos los mercados activos.
        Retorna (contadores, lista de nuevas oportunidades).
        """
        counts = {"markets_scanned": 0, "opportunities_found": 0, "errors": 0}
        new_opportunities: list[Opportunity] = []
        pending_paper: list[PendingValueBet] = []

        # Commission map se carga una vez por corrida (cambia rara vez).
        commission_map = await self._load_commission_map(db)

        # Get upcoming matches within valid window
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        from datetime import timedelta
        min_time = now + timedelta(minutes=self.min_minutes_to_kickoff)
        max_time = now + timedelta(minutes=self.max_minutes_to_kickoff)
        matches = await db.execute(
            select(Match)
            .join(Season, Match.season_id == Season.id)
            .join(League, Season.league_id == League.id)
            .where(
                Match.status == "scheduled",
                Match.commence_time > min_time,
                Match.commence_time <= max_time,
                League.detection_enabled.is_(True),
            )
        )

        for match in matches.scalars().all():
            try:
                found_opps = await self._detect_for_match(
                    db, match, commission_map, pending_paper
                )
                counts["opportunities_found"] += len(found_opps)
                new_opportunities.extend(found_opps)
            except Exception:
                logger.exception("Error detecting for match %s", match.id)
                counts["errors"] += 1

        # Portfolio sizing del batch completo: agrupa por match, aplica Kelly
        # fraccionado, cap por bet, y cap de exposición total considerando
        # PaperBets pendientes anteriores.
        if pending_paper:
            await self.paper.record_batch_value_bets(db, pending_paper)

        # Expire old opportunities
        expired = await self._expire_opportunities(db, now)
        counts["expired"] = expired

        await db.commit()
        return counts, new_opportunities

    async def _detect_for_match(
        self,
        db: AsyncSession,
        match: Match,
        commission_map: dict[str, float],
        pending_paper: list[PendingValueBet],
    ) -> list[Opportunity]:
        """Detecta value bets para todos los mercados de un partido."""
        new_opps: list[Opportunity] = []

        # Get all markets for this match
        markets_result = await db.execute(
            select(Market).where(Market.match_id == match.id, Market.active.is_(True))
        )

        for market in markets_result.scalars().all():
            value_bets = await self._detect_for_market(db, market, commission_map)
            for vb in value_bets:
                opp = await self._save_opportunity(db, vb, market, match)
                if opp:
                    new_opps.append(opp)
                    pending_paper.append(
                        PendingValueBet(opportunity=opp, vb=vb, match_id=match.id)
                    )

        return new_opps

    async def _detect_for_market(
        self, db: AsyncSession, market: Market, commission_map: dict[str, float]
    ) -> list[ValueBet]:
        """Detecta value bets para un mercado específico."""
        # Get all outcomes
        outcomes_result = await db.execute(
            select(Outcome).where(Outcome.market_id == market.id)
        )
        outcomes = outcomes_result.scalars().all()
        if not outcomes:
            return []

        outcome_keys = [o.key for o in outcomes]

        # Get latest odds per outcome per bookmaker
        odds_by_bookmaker = await self._get_latest_odds_by_bookmaker(db, outcomes)

        if self.reference_bookmaker:
            # Reference mode: compare every book vs reference (de-vigued) fair odds.
            # Needs reference + at least one other book, regardless of min_bookmakers.
            if self.reference_bookmaker not in odds_by_bookmaker:
                return []
            if len(odds_by_bookmaker) < 2:
                return []
            return detect_value_bets_vs_reference(
                odds_by_bookmaker=odds_by_bookmaker,
                outcome_keys=outcome_keys,
                reference_bookmaker=self.reference_bookmaker,
                min_value=self.min_value,
                commission_by_bookmaker=commission_map,
            )

        # Consensus mode (multi-book): gate on min_bookmakers.
        if len(odds_by_bookmaker) < self.min_bookmakers:
            return []

        sharps_result = await db.execute(
            select(Bookmaker).where(Bookmaker.is_sharp.is_(True))
        )
        sharp_keys = {b.key for b in sharps_result.scalars().all()}

        return detect_value_bets(
            odds_by_bookmaker=odds_by_bookmaker,
            outcome_keys=outcome_keys,
            sharp_bookmakers=sharp_keys,
            min_value=self.min_value,
            min_bookmakers=self.min_bookmakers,
            commission_by_bookmaker=commission_map,
        )

    async def _load_commission_map(self, db: AsyncSession) -> dict[str, float]:
        """
        {bookmaker_key: comisión efectiva (0-1)}.

        Resolución: `bookmaker.commission_pct` si > 0, sino
        `broker.default_commission_pct` si hay broker asociado. Books sin
        comisión quedan fuera del dict (se interpretan como 0 en los detectores).
        """
        result = await db.execute(
            select(Bookmaker).options(selectinload(Bookmaker.broker))
        )
        commissions: dict[str, float] = {}
        for bm in result.scalars().all():
            comm = float(bm.commission_pct or 0)
            if comm == 0 and bm.broker is not None:
                comm = float(bm.broker.default_commission_pct or 0)
            if comm > 0:
                commissions[bm.key] = comm
        return commissions

    async def _get_latest_odds_by_bookmaker(
        self, db: AsyncSession, outcomes: list[Outcome]
    ) -> dict[str, list[float]]:
        """
        Obtiene las últimas cuotas agrupadas por bookmaker.
        Retorna: {bookmaker_key: [odds_outcome_1, odds_outcome_2, ...]}
        """
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import func

        outcome_ids = [o.id for o in outcomes]
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff = now - timedelta(minutes=self.max_odds_age_minutes)

        # Get latest odds per outcome+bookmaker dentro de la ventana fresca.
        # Sin el filtro `captured_at >= cutoff`, un libro caido contribuye a
        # consenso con cuotas viejisimas -> value bets fantasma.
        latest_subq = (
            select(
                Odds.outcome_id,
                Odds.bookmaker_id,
                func.max(Odds.captured_at).label("max_captured"),
            )
            .where(
                Odds.outcome_id.in_(outcome_ids),
                Odds.captured_at >= cutoff,
            )
            .group_by(Odds.outcome_id, Odds.bookmaker_id)
            .subquery()
        )

        result = await db.execute(
            select(Odds, Bookmaker)
            .join(Bookmaker, Odds.bookmaker_id == Bookmaker.id)
            .join(
                latest_subq,
                (Odds.outcome_id == latest_subq.c.outcome_id)
                & (Odds.bookmaker_id == latest_subq.c.bookmaker_id)
                & (Odds.captured_at == latest_subq.c.max_captured),
            )
            # Excluye bookmakers inactivos (phantom books con commission=0).
            .where(Bookmaker.active.is_(True))
        )

        # Group by bookmaker
        bookmaker_odds: dict[str, dict[int, float]] = {}
        for odds, bookmaker in result.all():
            if bookmaker.key not in bookmaker_odds:
                bookmaker_odds[bookmaker.key] = {}
            bookmaker_odds[bookmaker.key][odds.outcome_id] = float(odds.price)

        # Convert to ordered list matching outcomes order
        odds_by_bookmaker: dict[str, list[float]] = {}
        for bk_key, odds_map in bookmaker_odds.items():
            # Only include bookmakers that have odds for ALL outcomes
            if all(o.id in odds_map for o in outcomes):
                odds_by_bookmaker[bk_key] = [odds_map[o.id] for o in outcomes]

        return odds_by_bookmaker

    async def _save_opportunity(
        self, db: AsyncSession, vb: ValueBet, market: Market, match: Match
    ) -> Opportunity | None:
        """Guarda o actualiza una oportunidad detectada. Retorna solo si es nueva."""
        # Get the outcome and bookmaker IDs
        outcome_result = await db.execute(
            select(Outcome).where(
                Outcome.market_id == market.id,
                Outcome.key == vb.outcome_key,
            )
        )
        outcome = outcome_result.scalar_one_or_none()
        if not outcome:
            return None

        bookmaker_result = await db.execute(
            select(Bookmaker).where(Bookmaker.key == vb.bookmaker_key)
        )
        bookmaker = bookmaker_result.scalar_one_or_none()
        if not bookmaker:
            return None

        # Check if this opportunity already exists (same outcome + bookmaker, still active)
        existing = await db.execute(
            select(Opportunity).where(
                Opportunity.outcome_id == outcome.id,
                Opportunity.bookmaker_id == bookmaker.id,
                Opportunity.status == "active",
            )
        )
        opp = existing.scalar_one_or_none()

        if opp:
            # Update existing — not a new opportunity
            opp.odds_price = Decimal(str(vb.bookmaker_odds))
            opp.consensus_prob = Decimal(str(vb.consensus_prob))
            opp.implied_prob = Decimal(str(vb.implied_prob))
            opp.value_pct = Decimal(str(vb.value_pct))
            opp.kelly_stake_pct = Decimal(str(vb.kelly_full))
            return None
        else:
            # Steam check: ¿los libros sharp se movieron rápido en este outcome?
            # Si sí, esta "value" puede ser una cuota soft a punto de corregirse.
            steam = await detect_steam_signal(db, outcome.id)
            # Create new. PaperBet se crea después en batch (record_batch_value_bets)
            # con sizing portfolio considerando todas las señales del ciclo.
            opp = Opportunity(
                outcome_id=outcome.id,
                bookmaker_id=bookmaker.id,
                odds_price=Decimal(str(vb.bookmaker_odds)),
                consensus_prob=Decimal(str(vb.consensus_prob)),
                implied_prob=Decimal(str(vb.implied_prob)),
                value_pct=Decimal(str(vb.value_pct)),
                kelly_stake_pct=Decimal(str(vb.kelly_full)),
                is_steam=steam.is_steam,
                expires_at=match.commence_time,
            )
            db.add(opp)
            await db.flush()
            return opp

    async def _expire_opportunities(self, db: AsyncSession, now: datetime) -> int:
        """Marca como expiradas las oportunidades de partidos que ya empezaron."""
        result = await db.execute(
            select(Opportunity).where(
                Opportunity.status == "active",
                Opportunity.expires_at <= now,
            )
        )
        expired = 0
        for opp in result.scalars().all():
            opp.status = "expired"
            opp.closed_at = now
            expired += 1
        return expired
