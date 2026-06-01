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
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.portfolio import PortfolioBet, allocate_portfolio
from app.core.value_detector import ValueBet
from app.models.arbitrage import ArbitrageOpportunity
from app.models.bookmaker import Bookmaker
from app.models.market import Market, MarketType, Outcome
from app.models.match import Match
from app.models.opportunity import Opportunity
from app.models.paper import PaperBet
from app.models.team import Team

logger = logging.getLogger(__name__)

# Default abstract stake per value bet when Kelly is 0/missing.
# Units = fraction of bankroll, so 0.01 = 1% flat.
DEFAULT_STAKE_UNITS = Decimal("0.01")

# Paper trading replica el comportamiento real del usuario: 1/4 Kelly con cap.
# Sin esto, paper apostaba `kelly_full` crudo (puede ser 20-30% del bankroll en
# señales fuertes), divergiendo del P&L que el usuario realmente realizaría.
PAPER_KELLY_FRACTION = Decimal("0.25")
PAPER_MAX_STAKE_UNITS = Decimal("0.05")  # cap 5% del bankroll por bet

# Cap de exposición total simultánea sobre value bets pending. Sumar Kelly individual
# en N señales de un día puede exceder fácilmente el bankroll; este cap modela el
# techo agregado que un operador disciplinado mantiene. Arbitraje queda fuera del
# cómputo (las legs están hedgeadas — el riesgo neto es muy menor que la suma).
PAPER_MAX_TOTAL_EXPOSURE_UNITS = Decimal("0.20")  # 20% del bankroll en juego


def _effective_commission(bookmaker: Bookmaker) -> Decimal:
    """Comisión efectiva: la del libro, o la del broker si el libro es 0 y hay broker.

    Refleja el patrón de `arbitrage_service` para que la comisión usada al
    detectar arbs sea la misma que se aplica al liquidar el paper bet.
    """
    bk_pct = bookmaker.commission_pct or Decimal("0")
    if bk_pct > 0:
        return bk_pct
    if bookmaker.broker is not None:
        return bookmaker.broker.default_commission_pct or Decimal("0")
    return Decimal("0")


@dataclass
class PendingValueBet:
    """Item interno: opportunity + value-bet para batch allocation."""

    opportunity: Opportunity
    vb: ValueBet
    match_id: int


class PaperTradingService:
    async def record_batch_value_bets(
        self,
        db: AsyncSession,
        items: list[PendingValueBet],
    ) -> list[PaperBet]:
        """Sizing portfolio en batch: agrupa por match, aplica caps y exposición total.

        Invocado al final de un ciclo de detección. Decide qué Opportunities
        merecen un PaperBet y con qué stake, considerando todas las señales
        simultáneas (no greedy first-come-first-served).
        """
        if not items:
            return []

        current_exposure = (
            await db.execute(
                select(func.coalesce(func.sum(PaperBet.stake_units), 0)).where(
                    PaperBet.source_type == "value",
                    PaperBet.result == "pending",
                )
            )
        ).scalar_one()
        available = float(PAPER_MAX_TOTAL_EXPOSURE_UNITS) - float(current_exposure)

        portfolio_input = [
            PortfolioBet(
                bet_id=str(it.opportunity.id),
                match_id=it.match_id,
                raw_kelly=it.vb.kelly_full,
            )
            for it in items
        ]
        allocations = allocate_portfolio(
            portfolio_input,
            available_exposure=available,
            kelly_fraction=float(PAPER_KELLY_FRACTION),
            per_bet_cap=float(PAPER_MAX_STAKE_UNITS),
        )
        alloc_by_id = {a.bet_id: a for a in allocations}

        # Pre-cargar bookmakers + broker para snapshotear commission_pct
        bk_ids = {it.opportunity.bookmaker_id for it in items}
        bookmakers = (
            await db.execute(
                select(Bookmaker)
                .options(selectinload(Bookmaker.broker))
                .where(Bookmaker.id.in_(bk_ids))
            )
        ).scalars().all()
        bk_by_id = {b.id: b for b in bookmakers}

        created: list[PaperBet] = []
        for it in items:
            alloc = alloc_by_id.get(str(it.opportunity.id))
            if alloc is None or alloc.skipped or alloc.stake <= 0:
                continue
            bk = bk_by_id.get(it.opportunity.bookmaker_id)
            commission = _effective_commission(bk) if bk else Decimal("0")
            paper = PaperBet(
                source_type="value",
                opportunity_id=it.opportunity.id,
                match_id=it.match_id,
                outcome_id=it.opportunity.outcome_id,
                bookmaker_id=it.opportunity.bookmaker_id,
                odds_taken=Decimal(str(it.vb.bookmaker_odds)),
                stake_units=Decimal(str(round(alloc.stake, 5))),
                ev_at_placement=Decimal(str(it.vb.value_pct)),
                commission_pct=commission,
            )
            db.add(paper)
            created.append(paper)
        if created:
            await db.flush()
        return created

    async def record_value_bet(
        self,
        db: AsyncSession,
        opportunity: Opportunity,
        vb: ValueBet,
        match_id: int,
    ) -> PaperBet | None:
        """Registra una paper bet a partir de una value bet recién detectada.

        Aplica cap de exposición total: si la suma de stakes pending de value bets
        ya alcanzó `PAPER_MAX_TOTAL_EXPOSURE_UNITS`, omite el registro.
        """
        if vb.kelly_full > 0:
            fractional = Decimal(str(vb.kelly_full)) * PAPER_KELLY_FRACTION
            desired_stake = min(fractional, PAPER_MAX_STAKE_UNITS)
        else:
            desired_stake = DEFAULT_STAKE_UNITS

        current_exposure = (
            await db.execute(
                select(func.coalesce(func.sum(PaperBet.stake_units), 0)).where(
                    PaperBet.source_type == "value",
                    PaperBet.result == "pending",
                )
            )
        ).scalar_one()
        current_exposure = Decimal(str(current_exposure))
        available = PAPER_MAX_TOTAL_EXPOSURE_UNITS - current_exposure

        if available <= 0:
            logger.info(
                "Paper exposure cap reached (%s units pending); skipping new value bet",
                current_exposure,
            )
            return None

        stake = min(desired_stake, available)

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
        # Pre-cargar outcomes y bookmakers (con broker) en lookups por key,
        # para evitar 2*N queries dentro del loop por leg.
        outcome_keys = [leg["outcome"] for leg in arb.legs]
        bk_keys = [leg["bookmaker"] for leg in arb.legs]
        outcomes = (
            await db.execute(
                select(Outcome).where(
                    Outcome.market_id == arb.market_id,
                    Outcome.key.in_(outcome_keys),
                )
            )
        ).scalars().all()
        outcome_by_key = {o.key: o for o in outcomes}
        bookmakers = (
            await db.execute(
                select(Bookmaker)
                .options(selectinload(Bookmaker.broker))
                .where(Bookmaker.key.in_(bk_keys))
            )
        ).scalars().all()
        bk_by_key = {b.key: b for b in bookmakers}

        papers: list[PaperBet] = []
        for leg in arb.legs:
            outcome = outcome_by_key.get(leg["outcome"])
            bookmaker = bk_by_key.get(leg["bookmaker"])
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
                commission_pct=_effective_commission(bookmaker),
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
        según el market_type: h2h (team_key o 'draw'), totals (over/under vs
        la línea en market.parameter), o void si empate a la línea. Mercados
        no soportados (p. ej. spreads sin point por outcome) se cuentan como
        skipped y el paper bet queda pending.
        """
        if match.home_score is None or match.away_score is None:
            return {"settled": 0, "skipped": 0}

        home = (await db.execute(select(Team).where(Team.id == match.home_team_id))).scalar_one()
        away = (await db.execute(select(Team).where(Team.id == match.away_team_id))).scalar_one()

        pending = (
            await db.execute(
                select(PaperBet, Outcome, Market, MarketType)
                .join(Outcome, Outcome.id == PaperBet.outcome_id)
                .join(Market, Market.id == Outcome.market_id)
                .join(MarketType, MarketType.id == Market.market_type_id)
                .where(PaperBet.match_id == match.id, PaperBet.result == "pending")
            )
        ).all()

        settled = 0
        skipped = 0
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for paper, outcome, market, market_type in pending:
            verdict = _decide_paper_bet_result(
                market_type.key,
                outcome.key,
                market.parameter,
                match.home_score,
                match.away_score,
                home.canonical_name,
                away.canonical_name,
            )
            if verdict is None:
                skipped += 1
                continue

            if verdict == "won":
                paper.result = "won"
                # Aplicar la comisión snapshoteada al placement. Coherente con el
                # detector de arbs/value: éste evalúa profit_pct con cuotas
                # efectivas (1 + (odds-1)*(1-c)); el settle debe pagar igual,
                # sino el ROI paper queda inflado vs la operación real.
                # Back-compat: paper bets viejas sin commission_pct usan 0.
                commission = paper.commission_pct or Decimal("0")
                gross_profit = paper.stake_units * (paper.odds_taken - Decimal("1"))
                paper.profit_units = gross_profit * (Decimal("1") - commission)
            elif verdict == "lost":
                paper.result = "lost"
                paper.profit_units = -paper.stake_units
            else:  # void (push)
                paper.result = "void"
                paper.profit_units = Decimal("0")
            paper.resolved_at = now
            settled += 1

        return {"settled": settled, "skipped": skipped}

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


def _decide_paper_bet_result(
    market_type_key: str,
    outcome_key: str,
    market_parameter,
    home_score: int,
    away_score: int,
    home_name: str,
    away_name: str,
) -> str | None:
    """Devuelve 'won' | 'lost' | 'void' (push) o None si no se sabe liquidar.

    Soporta h2h y totals. Para otros mercados (spreads, BTTS, etc.) devuelve
    None y el caller cuenta el paper bet como skipped (queda `pending`).
    """
    key = outcome_key.lower()

    if market_type_key == "h2h":
        if home_score > away_score:
            winner_side = "home"
        elif away_score > home_score:
            winner_side = "away"
        else:
            winner_side = "draw"

        home_slug = home_name.lower().replace(" ", "_")
        away_slug = away_name.lower().replace(" ", "_")

        # Las outcomes llegan en dos convenciones: posicional ("home"/"away"/
        # "draw", canonizada por el normalizador) o slug del nombre del equipo
        # ("atlanta_braves"). El settlement debe entender ambas; una key que no
        # corresponda a ningún lado se devuelve como None (skip → queda pending),
        # nunca "lost" por defecto, para no corromper ambas legs de un arb.
        if key in ("home", "away", "draw"):
            return "won" if key == winner_side else "lost"
        if key in (home_slug, away_slug, "draw"):
            winner_slug = {"home": home_slug, "away": away_slug, "draw": "draw"}[
                winner_side
            ]
            return "won" if key == winner_slug else "lost"
        return None

    if market_type_key == "totals":
        if market_parameter is None:
            return None
        try:
            line = float(market_parameter)
        except (TypeError, ValueError):
            return None
        total = home_score + away_score
        if total == line:
            return "void"
        if key == "over":
            return "won" if total > line else "lost"
        if key == "under":
            return "won" if total < line else "lost"
        return None

    return None
