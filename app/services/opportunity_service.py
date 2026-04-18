"""Servicio de detección de oportunidades: consensus → detect → save."""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.value_detector import (
    ValueBet,
    detect_value_bets,
    detect_value_bets_vs_reference,
)
from app.models.bookmaker import Bookmaker
from app.models.market import Market, Odds, Outcome
from app.models.match import Match
from app.models.opportunity import Opportunity
from app.services.paper_trading_service import PaperTradingService

logger = logging.getLogger(__name__)


class OpportunityDetectionService:
    def __init__(
        self,
        min_value: float = 0.05,
        min_bookmakers: int = 5,
        min_minutes_to_kickoff: int = 15,
        max_minutes_to_kickoff: int = 10080,  # 7 days — tighten to 48h for real betting
        reference_bookmaker: str | None = None,
    ):
        self.min_value = min_value
        self.min_bookmakers = min_bookmakers
        self.min_minutes_to_kickoff = min_minutes_to_kickoff
        self.max_minutes_to_kickoff = max_minutes_to_kickoff
        self.reference_bookmaker = reference_bookmaker
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

        # Get upcoming matches within valid window
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        from datetime import timedelta
        min_time = now + timedelta(minutes=self.min_minutes_to_kickoff)
        max_time = now + timedelta(minutes=self.max_minutes_to_kickoff)
        matches = await db.execute(
            select(Match).where(
                Match.status == "scheduled",
                Match.commence_time > min_time,
                Match.commence_time <= max_time,
            )
        )

        for match in matches.scalars().all():
            try:
                found_opps = await self._detect_for_match(db, match)
                counts["opportunities_found"] += len(found_opps)
                new_opportunities.extend(found_opps)
            except Exception as e:
                logger.error(f"Error detecting for match {match.id}: {e}")
                counts["errors"] += 1

        # Expire old opportunities
        expired = await self._expire_opportunities(db, now)
        counts["expired"] = expired

        await db.commit()
        return counts, new_opportunities

    async def _detect_for_match(
        self, db: AsyncSession, match: Match
    ) -> list[Opportunity]:
        """Detecta value bets para todos los mercados de un partido."""
        new_opps: list[Opportunity] = []

        # Get all markets for this match
        markets_result = await db.execute(
            select(Market).where(Market.match_id == match.id, Market.active.is_(True))
        )

        for market in markets_result.scalars().all():
            value_bets = await self._detect_for_market(db, market)
            for vb in value_bets:
                opp = await self._save_opportunity(db, vb, market, match)
                if opp:
                    new_opps.append(opp)

        return new_opps

    async def _detect_for_market(self, db: AsyncSession, market: Market) -> list[ValueBet]:
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
        )

    async def _get_latest_odds_by_bookmaker(
        self, db: AsyncSession, outcomes: list[Outcome]
    ) -> dict[str, list[float]]:
        """
        Obtiene las últimas cuotas agrupadas por bookmaker.
        Retorna: {bookmaker_key: [odds_outcome_1, odds_outcome_2, ...]}
        """
        from sqlalchemy import func

        outcome_ids = [o.id for o in outcomes]

        # Get latest odds per outcome+bookmaker
        latest_subq = (
            select(
                Odds.outcome_id,
                Odds.bookmaker_id,
                func.max(Odds.captured_at).label("max_captured"),
            )
            .where(Odds.outcome_id.in_(outcome_ids))
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
            # Create new
            opp = Opportunity(
                outcome_id=outcome.id,
                bookmaker_id=bookmaker.id,
                odds_price=Decimal(str(vb.bookmaker_odds)),
                consensus_prob=Decimal(str(vb.consensus_prob)),
                implied_prob=Decimal(str(vb.implied_prob)),
                value_pct=Decimal(str(vb.value_pct)),
                kelly_stake_pct=Decimal(str(vb.kelly_full)),
                expires_at=match.commence_time,
            )
            db.add(opp)
            await db.flush()
            await self.paper.record_value_bet(db, opp, vb, match.id)
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
