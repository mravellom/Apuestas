"""Paper trading: registra y liquida apuestas simuladas.

Flujo:
1. Cuando el engine detecta una oportunidad (value o arbitraje), se registra
   automáticamente una PaperBet con stake Kelly y EV al momento.
2. Cuando el partido termina (status='completed' con scores), se liquida:
   ganadora, perdedora, o void (empate en 2-way).

No requiere usuario ni bankroll — es tracking puro para validar si el
engine genera ROI positivo antes de arriesgar dinero real.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.value_detector import ValueBet
from app.models.arbitrage import ArbitrageOpportunity
from app.models.bookmaker import Bookmaker
from app.models.market import Outcome
from app.models.match import Match
from app.models.opportunity import Opportunity
from app.models.paper import PaperBet
from app.models.team import Team

logger = logging.getLogger(__name__)

# Default abstract stake per value bet when Kelly is 0/missing.
# Units = fraction of bankroll, so 0.01 = 1% flat.
DEFAULT_STAKE_UNITS = Decimal("0.01")


class PaperTradingService:
    async def record_value_bet(
        self,
        db: AsyncSession,
        opportunity: Opportunity,
        vb: ValueBet,
        match_id: int,
    ) -> PaperBet:
        """Registra una paper bet a partir de una value bet recién detectada."""
        stake = Decimal(str(vb.kelly_full)) if vb.kelly_full > 0 else DEFAULT_STAKE_UNITS
        paper = PaperBet(
            source_type="value",
            opportunity_id=opportunity.id,
            match_id=match_id,
            outcome_id=opportunity.outcome_id,
            bookmaker_id=opportunity.bookmaker_id,
            odds_taken=Decimal(str(vb.bookmaker_odds)),
            stake_units=stake,
            ev_at_placement=Decimal(str(vb.value_pct)),
        )
        db.add(paper)
        await db.flush()
        return paper

    async def record_arbitrage(
        self,
        db: AsyncSession,
        arb: ArbitrageOpportunity,
    ) -> list[PaperBet]:
        """Registra una paper bet por cada leg del arbitraje."""
        papers: list[PaperBet] = []
        for leg in arb.legs:
            # Resolve outcome and bookmaker IDs from the stored leg data
            outcome = (
                await db.execute(
                    select(Outcome).where(Outcome.market_id == arb.market_id, Outcome.key == leg["outcome"])
                )
            ).scalar_one_or_none()
            bookmaker = (
                await db.execute(select(Bookmaker).where(Bookmaker.key == leg["bookmaker"]))
            ).scalar_one_or_none()
            if not outcome or not bookmaker:
                continue
            paper = PaperBet(
                source_type="arbitrage",
                arbitrage_id=arb.id,
                match_id=arb.match_id,
                outcome_id=outcome.id,
                bookmaker_id=bookmaker.id,
                odds_taken=Decimal(str(leg["odds"])),
                stake_units=Decimal(str(leg["stake_pct"])),
                ev_at_placement=Decimal(str(arb.profit_pct)) / Decimal("100"),
            )
            db.add(paper)
            papers.append(paper)
        await db.flush()
        return papers

    async def settle_match(
        self,
        db: AsyncSession,
        match: Match,
    ) -> dict[str, int]:
        """Liquida todas las paper bets pendientes de un partido terminado.

        Requiere match.home_score y match.away_score. Decide el outcome ganador
        comparando scores. Asume mercado h2h con outcome.key ∈ {team_key, 'draw'}.
        """
        if match.home_score is None or match.away_score is None:
            return {"settled": 0, "skipped": 0}

        home = (await db.execute(select(Team).where(Team.id == match.home_team_id))).scalar_one()
        away = (await db.execute(select(Team).where(Team.id == match.away_team_id))).scalar_one()

        if match.home_score > match.away_score:
            winning_key = home.canonical_name.lower().replace(" ", "_")
        elif match.away_score > match.home_score:
            winning_key = away.canonical_name.lower().replace(" ", "_")
        else:
            winning_key = "draw"

        pending = (
            await db.execute(
                select(PaperBet, Outcome)
                .join(Outcome, Outcome.id == PaperBet.outcome_id)
                .where(PaperBet.match_id == match.id, PaperBet.result == "pending")
            )
        ).all()

        settled = 0
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for paper, outcome in pending:
            if outcome.key.lower() == winning_key:
                paper.result = "won"
                paper.profit_units = paper.stake_units * (paper.odds_taken - Decimal("1"))
            else:
                paper.result = "lost"
                paper.profit_units = -paper.stake_units
            paper.resolved_at = now
            settled += 1

        return {"settled": settled, "skipped": 0}

    async def settle_all_completed(self, db: AsyncSession) -> dict[str, int]:
        """Liquida todos los partidos completados con scores y apuestas pendientes."""
        matches_with_pending = (
            await db.execute(
                select(Match)
                .join(PaperBet, PaperBet.match_id == Match.id)
                .where(
                    Match.status == "completed",
                    Match.home_score.is_not(None),
                    Match.away_score.is_not(None),
                    PaperBet.result == "pending",
                )
                .distinct()
            )
        ).scalars().all()

        total = {"settled": 0, "matches": 0}
        for m in matches_with_pending:
            r = await self.settle_match(db, m)
            total["settled"] += r["settled"]
            total["matches"] += 1
        await db.commit()
        return total
