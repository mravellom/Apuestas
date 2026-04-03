"""Servicio de ingesta de cuotas: fetch → normalize → save."""

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import DataSourceAdapter, RawOddsData
from app.adapters.normalizer import TeamNormalizer
from app.models.bookmaker import Bookmaker
from app.models.market import Market, MarketType, Odds, Outcome
from app.models.match import Match
from app.models.sport import League, Season, Sport

logger = logging.getLogger(__name__)


class OddsIngestionService:
    def __init__(self, adapter: DataSourceAdapter, normalizer: TeamNormalizer | None = None):
        self.adapter = adapter
        self.normalizer = normalizer or TeamNormalizer()

    async def ingest_odds(
        self,
        db: AsyncSession,
        sport_key: str = "football",
        league_keys: list[str] | None = None,
        regions: list[str] | None = None,
        markets: list[str] | None = None,
    ) -> dict[str, int]:
        """
        Pipeline completo: fetch → normalize → save.
        Retorna contadores de lo procesado.
        """
        regions = regions or ["eu", "uk"]
        markets = markets or ["h2h"]

        counts = {"events": 0, "odds_saved": 0, "errors": 0}

        # Get sport
        sport = await self._get_sport(db, sport_key)
        if not sport:
            logger.warning(f"Sport '{sport_key}' not found in DB")
            return counts

        # Fetch from all configured leagues or use provided ones
        if league_keys is None:
            result = await db.execute(
                select(League).where(League.sport_id == sport.id, League.active.is_(True))
            )
            league_keys = [lg.key for lg in result.scalars().all()]

        for league_key in league_keys:
            try:
                raw_odds = await self.adapter.fetch_odds(league_key, regions, markets)
                if not raw_odds:
                    continue

                # Group by event (external_id)
                events: dict[str, list[RawOddsData]] = {}
                for rod in raw_odds:
                    eid = rod.external_id or f"{rod.home_team}_{rod.away_team}_{rod.commence_time}"
                    events.setdefault(eid, []).append(rod)

                for event_id, odds_list in events.items():
                    try:
                        await self._process_event(db, sport, league_key, event_id, odds_list)
                        counts["events"] += 1
                        counts["odds_saved"] += len(odds_list)
                    except Exception as e:
                        logger.error(f"Error processing event {event_id}: {e}")
                        counts["errors"] += 1

                await db.commit()
            except Exception as e:
                logger.error(f"Error fetching odds for {league_key}: {e}")
                counts["errors"] += 1

        return counts

    async def _process_event(
        self,
        db: AsyncSession,
        sport: Sport,
        league_key: str,
        event_id: str,
        odds_list: list[RawOddsData],
    ):
        """Procesa un evento: crea/actualiza match, markets, outcomes, odds."""
        first = odds_list[0]

        # Resolve league + season
        season = await self._get_or_create_season(db, league_key)
        if not season:
            return

        # Resolve teams
        home_team_id = await self.normalizer.get_or_create_team(
            first.home_team, first.source, sport.id, db
        )
        away_team_id = await self.normalizer.get_or_create_team(
            first.away_team, first.source, sport.id, db
        )

        # Get or create match
        match = await self._get_or_create_match(
            db, season.id, home_team_id, away_team_id,
            first.commence_time, first.external_id
        )

        # Process each odds entry (one per bookmaker+market)
        for rod in odds_list:
            await self._save_odds(db, match, rod)

        await db.flush()

    async def _save_odds(self, db: AsyncSession, match: Match, rod: RawOddsData):
        """Guarda las cuotas de un bookmaker para un mercado."""
        # Get or create market type
        market_type = await self._get_market_type(db, rod.market_type)
        if not market_type:
            return

        # Get or create bookmaker
        bookmaker = await self._get_or_create_bookmaker(db, rod.bookmaker)

        # Get or create market
        market = await self._get_or_create_market(
            db, match.id, market_type.id,
            Decimal(str(rod.parameter)) if rod.parameter is not None else None
        )

        # Save each outcome + odds
        for raw_outcome in rod.outcomes:
            outcome_key = self._normalize_outcome_key(raw_outcome.name, rod.market_type)
            outcome = await self._get_or_create_outcome(
                db, market.id, outcome_key, raw_outcome.name
            )

            odds = Odds(
                outcome_id=outcome.id,
                bookmaker_id=bookmaker.id,
                price=Decimal(str(raw_outcome.price)),
                source=rod.source,
            )
            db.add(odds)

    async def _get_sport(self, db: AsyncSession, sport_key: str) -> Sport | None:
        result = await db.execute(select(Sport).where(Sport.key == sport_key))
        return result.scalar_one_or_none()

    async def _get_or_create_season(self, db: AsyncSession, league_key: str) -> Season | None:
        result = await db.execute(
            select(Season)
            .join(League)
            .where(League.key == league_key, Season.active.is_(True))
            .order_by(Season.id.desc())
        )
        return result.scalar_one_or_none()

    async def _get_or_create_match(
        self, db: AsyncSession, season_id: int,
        home_team_id: int, away_team_id: int,
        commence_time: datetime, external_id: str | None
    ) -> Match:
        # Try to find by external_id first
        if external_id:
            result = await db.execute(
                select(Match).where(Match.external_id == external_id)
            )
            match = result.scalar_one_or_none()
            if match:
                return match

        # Try by teams + time
        result = await db.execute(
            select(Match).where(
                Match.season_id == season_id,
                Match.home_team_id == home_team_id,
                Match.away_team_id == away_team_id,
                Match.commence_time == commence_time,
            )
        )
        match = result.scalar_one_or_none()
        if match:
            if external_id and not match.external_id:
                match.external_id = external_id
            return match

        match = Match(
            external_id=external_id,
            season_id=season_id,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            commence_time=commence_time,
        )
        db.add(match)
        await db.flush()
        return match

    async def _get_market_type(self, db: AsyncSession, key: str) -> MarketType | None:
        result = await db.execute(select(MarketType).where(MarketType.key == key))
        return result.scalar_one_or_none()

    async def _get_or_create_bookmaker(self, db: AsyncSession, key: str) -> Bookmaker:
        result = await db.execute(select(Bookmaker).where(Bookmaker.key == key))
        bk = result.scalar_one_or_none()
        if bk:
            return bk
        bk = Bookmaker(key=key, name=key.replace("_", " ").title())
        db.add(bk)
        await db.flush()
        return bk

    async def _get_or_create_market(
        self, db: AsyncSession, match_id: int, market_type_id: int,
        parameter: Decimal | None
    ) -> Market:
        query = select(Market).where(
            Market.match_id == match_id,
            Market.market_type_id == market_type_id,
        )
        if parameter is not None:
            query = query.where(Market.parameter == parameter)
        else:
            query = query.where(Market.parameter.is_(None))

        result = await db.execute(query)
        market = result.scalar_one_or_none()
        if market:
            return market

        market = Market(
            match_id=match_id,
            market_type_id=market_type_id,
            parameter=parameter,
        )
        db.add(market)
        await db.flush()
        return market

    async def _get_or_create_outcome(
        self, db: AsyncSession, market_id: int, key: str, name: str
    ) -> Outcome:
        result = await db.execute(
            select(Outcome).where(Outcome.market_id == market_id, Outcome.key == key)
        )
        outcome = result.scalar_one_or_none()
        if outcome:
            return outcome

        outcome = Outcome(market_id=market_id, key=key, name=name)
        db.add(outcome)
        await db.flush()
        return outcome

    @staticmethod
    def _normalize_outcome_key(name: str, market_type: str) -> str:
        """Normaliza el nombre del outcome a una key estándar."""
        name_lower = name.lower().strip()
        if market_type == "h2h":
            if name_lower == "draw":
                return "draw"
            # For h2h, first outcome is typically home, last is away
            # But The Odds API uses team names, so we keep them as-is
            return name_lower.replace(" ", "_")
        elif market_type == "totals":
            if "over" in name_lower:
                return "over"
            return "under"
        elif market_type == "spreads":
            return name_lower.replace(" ", "_")
        return name_lower.replace(" ", "_")
