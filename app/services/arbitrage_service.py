"""Servicio de detección de arbitraje: busca surebets entre bookmakers."""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.arbitrage import ArbOpportunity, detect_arbitrage
from app.models.arbitrage import ArbitrageOpportunity
from app.models.bookmaker import Bookmaker
from app.models.market import Market, Odds, Outcome
from app.models.match import Match
from app.models.sport import League, Season
from app.services.paper_trading_service import PaperTradingService

logger = logging.getLogger(__name__)


class ArbitrageDetectionService:
    def __init__(
        self,
        min_profit_pct: float = 0.5,
        min_bookmakers: int = 5,
        min_minutes_to_kickoff: int = 15,
        max_minutes_to_kickoff: int = 10080,
        max_odds_age_minutes: int = 30,
    ):
        self.min_profit_pct = min_profit_pct
        self.min_bookmakers = min_bookmakers
        self.min_minutes_to_kickoff = min_minutes_to_kickoff
        self.max_minutes_to_kickoff = max_minutes_to_kickoff
        self.max_odds_age_minutes = max_odds_age_minutes
        self.paper = PaperTradingService()

    async def detect_all(
        self, db: AsyncSession
    ) -> tuple[dict[str, int], list[ArbitrageOpportunity]]:
        """
        Escanea todos los mercados activos buscando arbitraje.
        Returns: (counters, list of new ArbitrageOpportunity)
        """
        counts = {"markets_scanned": 0, "arbs_found": 0, "errors": 0}
        new_arbs: list[ArbitrageOpportunity] = []

        commission_map = await self._load_commission_map(db)

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        min_time = now + timedelta(minutes=self.min_minutes_to_kickoff)
        max_time = now + timedelta(minutes=self.max_minutes_to_kickoff)

        matches = (
            await db.execute(
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
        ).scalars().all()

        for match in matches:
            try:
                found, scanned = await self._detect_for_match(db, match, commission_map)
                counts["markets_scanned"] += scanned
                counts["arbs_found"] += len(found)
                new_arbs.extend(found)
            except Exception as e:
                logger.error("Error detecting arb for match %d: %s", match.id, e)
                counts["errors"] += 1

        # Expire old arbs
        expired = await self._expire_arbs(db, now)
        counts["expired"] = expired

        await db.commit()
        return counts, new_arbs

    async def _detect_for_match(
        self, db: AsyncSession, match: Match, commission_map: dict[str, float]
    ) -> tuple[list[ArbitrageOpportunity], int]:
        new_arbs: list[ArbitrageOpportunity] = []

        markets = (
            await db.execute(
                select(Market).where(
                    Market.match_id == match.id, Market.active.is_(True)
                )
            )
        ).scalars().all()

        for market in markets:
            arb = await self._detect_for_market(db, market, commission_map)
            if arb:
                saved = await self._save_arb(db, arb, market, match)
                if saved:
                    new_arbs.append(saved)

        return new_arbs, len(markets)

    async def _detect_for_market(
        self, db: AsyncSession, market: Market, commission_map: dict[str, float]
    ) -> ArbOpportunity | None:
        outcomes = (
            await db.execute(
                select(Outcome).where(Outcome.market_id == market.id)
            )
        ).scalars().all()

        if not outcomes:
            return None

        outcome_keys = [o.key for o in outcomes]
        outcome_names = [o.name for o in outcomes]

        odds_by_bookmaker = await self._get_latest_odds_by_bookmaker(db, outcomes)

        return detect_arbitrage(
            odds_by_bookmaker=odds_by_bookmaker,
            outcome_keys=outcome_keys,
            outcome_names=outcome_names,
            min_profit_pct=self.min_profit_pct,
            min_bookmakers=self.min_bookmakers,
            commission_by_bookmaker=commission_map,
        )

    async def _load_commission_map(self, db: AsyncSession) -> dict[str, float]:
        """
        {bookmaker_key: comisión efectiva (0-1)} resolviendo bookmaker.commission_pct
        con fallback a broker.default_commission_pct. Books con 0 quedan fuera.
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
        from sqlalchemy import func

        outcome_ids = [o.id for o in outcomes]
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            minutes=self.max_odds_age_minutes
        )

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
        )

        bookmaker_odds: dict[str, dict[int, float]] = {}
        for odds, bookmaker in result.all():
            if bookmaker.key not in bookmaker_odds:
                bookmaker_odds[bookmaker.key] = {}
            bookmaker_odds[bookmaker.key][odds.outcome_id] = float(odds.price)

        odds_by_bookmaker: dict[str, list[float]] = {}
        for bk_key, odds_map in bookmaker_odds.items():
            if all(o.id in odds_map for o in outcomes):
                odds_by_bookmaker[bk_key] = [odds_map[o.id] for o in outcomes]

        return odds_by_bookmaker

    async def _save_arb(
        self,
        db: AsyncSession,
        arb: ArbOpportunity,
        market: Market,
        match: Match,
    ) -> ArbitrageOpportunity | None:
        # Check if already exists for this market
        existing = (
            await db.execute(
                select(ArbitrageOpportunity).where(
                    ArbitrageOpportunity.match_id == match.id,
                    ArbitrageOpportunity.market_id == market.id,
                    ArbitrageOpportunity.status == "active",
                )
            )
        ).scalar_one_or_none()

        legs_data = [
            {
                "outcome": leg.outcome_key,
                "outcome_name": leg.outcome_name,
                "bookmaker": leg.bookmaker_key,
                "odds": leg.best_odds,
                "stake_pct": leg.stake_pct,
            }
            for leg in arb.legs
        ]

        if existing:
            existing.total_implied = Decimal(str(arb.total_implied))
            existing.profit_pct = Decimal(str(arb.profit_pct))
            existing.legs = legs_data
            return None  # updated, not new
        else:
            record = ArbitrageOpportunity(
                match_id=match.id,
                market_id=market.id,
                total_implied=Decimal(str(arb.total_implied)),
                profit_pct=Decimal(str(arb.profit_pct)),
                num_outcomes=arb.num_outcomes,
                legs=legs_data,
                expires_at=match.commence_time,
            )
            db.add(record)
            await db.flush()
            await self.paper.record_arbitrage(db, record)
            return record

    async def _expire_arbs(self, db: AsyncSession, now: datetime) -> int:
        result = (
            await db.execute(
                select(ArbitrageOpportunity).where(
                    ArbitrageOpportunity.status == "active",
                    ArbitrageOpportunity.expires_at <= now,
                )
            )
        ).scalars().all()

        for arb in result:
            arb.status = "expired"
            arb.closed_at = now

        return len(result)
