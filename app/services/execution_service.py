"""
Ejecución de apuestas reales: traduce oportunidades (arb o value) en registros
`BetTracking` y gestiona el ciclo de vida del capital reservado en el bankroll.

Flujo manual (único soportado hoy):
  1. execute_arbitrage_manual() — crea N BetTracking en status='pending' con el
     capital reservado. Devuelve un ExecutionPlan con instrucciones legibles.
  2. mark_leg_placed() — usuario confirma que colocó la apuesta en el libro
     con una cuota real (potencialmente distinta a la detectada).
  3. mark_leg_rejected() — libera el capital reservado de ese leg. Si el resto
     del arb ya está placed, el llamador decide si rebalancear manualmente o
     aceptar exposición unilateral.
  4. settle_leg() — tras resultado del partido, liquida ganancia/pérdida real
     y devuelve capital a current_amount.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.arbitrage import ArbitrageOpportunity
from app.models.bookmaker import Bookmaker
from app.models.market import Market, MarketType, Odds, Outcome
from app.models.match import Match
from app.models.opportunity import BetTracking
from app.models.team import Team
from app.models.user import Bankroll
from app.services.arbitrage_service import ArbitrageDetectionService, RevalidationResult


class ExecutionError(Exception):
    """Errores de negocio durante ejecución (bankroll insuficiente, arb inactivo, etc)."""


class StaleArbError(ExecutionError):
    """El arb cayó de valor pero sigue siendo positivo — requiere force=True para continuar."""

    def __init__(self, revalidation: RevalidationResult):
        self.revalidation = revalidation
        super().__init__(
            f"Arb is stale: profit_pct dropped from {revalidation.detected_profit_pct:.2f}% "
            f"to {revalidation.current_profit_pct:.2f}%. Pass force=True to execute anyway."
        )


class DeadArbError(ExecutionError):
    def __init__(self, revalidation: RevalidationResult):
        self.revalidation = revalidation
        super().__init__(
            f"Arb is dead: current profit_pct={revalidation.current_profit_pct:.2f}% "
            f"vs detected {revalidation.detected_profit_pct:.2f}%"
        )


@dataclass
class LegInstruction:
    bet_id: int
    bookmaker_key: str
    bookmaker_name: str
    outcome_key: str
    outcome_name: str
    stake_amount: Decimal
    target_odds: Decimal
    min_acceptable_odds: Decimal
    commission_pct: Decimal


@dataclass
class OutcomeScenario:
    """P&L si `outcome_key` termina ganando, dado el estado actual de legs placed."""
    outcome_key: str
    outcome_name: str
    pnl: Decimal
    covered: bool  # tenemos un leg placed que gana si este outcome wins


@dataclass
class LegSummary:
    bet_id: int
    outcome_key: str
    outcome_name: str
    bookmaker_key: str
    bookmaker_name: str
    stake_amount: Decimal
    status: str
    odds_effective: Decimal | None  # placement si placed, detection si aún pending
    commission_pct: Decimal


@dataclass
class ReplacementOption:
    bookmaker_key: str
    bookmaker_name: str
    odds: Decimal
    commission_pct: Decimal


@dataclass
class ReplacementSuggestion:
    """Alternativas para cubrir un leg que quedó rejected."""
    outcome_key: str
    outcome_name: str
    rejected_bookmaker_key: str
    alternatives: list[ReplacementOption] = field(default_factory=list)


@dataclass
class ExposureSummary:
    arbitrage_id: int
    currency: str
    is_partial_fill: bool
    any_rejected: bool
    all_placed: bool
    total_placed_stake: Decimal
    worst_case_pnl: Decimal
    best_case_pnl: Decimal
    scenarios: list[OutcomeScenario] = field(default_factory=list)
    legs: list[LegSummary] = field(default_factory=list)
    replacement_suggestions: list[ReplacementSuggestion] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    arbitrage_id: int
    match_label: str
    market_type: str
    total_stake: Decimal
    currency: str
    expected_profit: Decimal
    profit_pct: Decimal
    legs: list[LegInstruction] = field(default_factory=list)


class ExecutionService:
    # Tolerancia de cuota: si el libro da menos de (target × (1 − tolerance)),
    # el usuario debería rechazar. 1% cubre movimientos normales sin matar arbs
    # marginales.
    ODDS_TOLERANCE = Decimal("0.01")

    async def execute_arbitrage_manual(
        self,
        db: AsyncSession,
        *,
        arbitrage_id: int,
        user_id,
        bankroll_id: int,
        total_stake: Decimal,
        force_if_stale: bool = False,
    ) -> ExecutionPlan:
        arb = await db.get(ArbitrageOpportunity, arbitrage_id)
        if arb is None:
            raise ExecutionError(f"Arbitrage {arbitrage_id} not found")
        if arb.status != "active":
            raise ExecutionError(f"Arbitrage {arbitrage_id} is {arb.status}, not active")

        # Revalidación pre-ejecución: las cuotas en DB pueden haber movido desde
        # que se detectó. Dead → siempre bloquea; stale → requiere force_if_stale.
        arb_svc = ArbitrageDetectionService()
        revalidation = await arb_svc.revalidate_arb(db, arb.id)
        if revalidation.status == "dead":
            raise DeadArbError(revalidation)
        if revalidation.status == "stale" and not force_if_stale:
            raise StaleArbError(revalidation)

        # Lock del bankroll a nivel DB: todas las operaciones que leen-modifican
        # bankroll (execute, reject, settle) lo hacen bajo este lock para evitar
        # lost updates en concurrencia. En sqlite el FOR UPDATE es no-op pero
        # en postgres serializa las requests sobre el mismo row.
        bankroll = (
            await db.execute(
                select(Bankroll).with_for_update().where(Bankroll.id == bankroll_id)
            )
        ).scalar_one_or_none()
        if bankroll is None or bankroll.user_id != user_id:
            raise ExecutionError("Bankroll not found or not owned by user")

        # Idempotencia: si el usuario ya tiene bets vivos para este arb, no
        # crear duplicados (protege contra doble click / retry automático).
        # Estados terminales (rejected, settled, void) no bloquean — el usuario
        # puede reintentar un arb tras rechazarlo todo.
        existing = (
            await db.execute(
                select(BetTracking.id).where(
                    BetTracking.user_id == user_id,
                    BetTracking.arbitrage_id == arb.id,
                    BetTracking.status.in_(("pending", "placed", "confirmed")),
                )
            )
        ).first()
        if existing is not None:
            raise ExecutionError(
                f"Arbitrage {arb.id} already has active bets for this user; "
                f"reject or settle them before re-executing."
            )

        if bankroll.available_amount < total_stake:
            raise ExecutionError(
                f"Insufficient bankroll: available={bankroll.available_amount} "
                f"requested={total_stake}"
            )

        match = await db.get(Match, arb.match_id)
        market = await db.get(Market, arb.market_id)
        market_type = await db.get(MarketType, market.market_type_id) if market else None
        home = await db.get(Team, match.home_team_id) if match else None
        away = await db.get(Team, match.away_team_id) if match else None
        match_label = (
            f"{home.canonical_name} vs {away.canonical_name}" if home and away else ""
        )

        # Map bookmaker keys → Bookmaker objects for FK + commission snapshot.
        # Broker eager-loaded para resolver comisión sin queries extra por leg.
        bk_keys = {leg["bookmaker"] for leg in arb.legs}
        bk_rows = (
            await db.execute(
                select(Bookmaker)
                .options(selectinload(Bookmaker.broker))
                .where(Bookmaker.key.in_(bk_keys))
            )
        ).scalars().all()
        bookmaker_map = {b.key: b for b in bk_rows}

        # Outcomes for this market — match by key.
        outcomes = (
            await db.execute(select(Outcome).where(Outcome.market_id == arb.market_id))
        ).scalars().all()
        outcome_map = {o.key: o for o in outcomes}

        legs_out: list[LegInstruction] = []
        created_bets: list[BetTracking] = []

        for leg_data in arb.legs:
            bk_key = leg_data["bookmaker"]
            outcome_key = leg_data["outcome"]
            stake_pct = Decimal(str(leg_data["stake_pct"]))
            odds = Decimal(str(leg_data["odds"]))

            stake = (total_stake * stake_pct).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            bookmaker = bookmaker_map.get(bk_key)
            outcome = outcome_map.get(outcome_key)
            if bookmaker is None or outcome is None:
                raise ExecutionError(
                    f"Cannot resolve bookmaker '{bk_key}' or outcome '{outcome_key}' for arb {arbitrage_id}"
                )

            # Snapshot de comisión efectiva: commission_pct del book si > 0,
            # o default_commission_pct del broker si hay uno vinculado.
            commission = bookmaker.commission_pct or Decimal("0")
            if commission == 0 and bookmaker.broker is not None:
                commission = bookmaker.broker.default_commission_pct or Decimal("0")

            bet = BetTracking(
                user_id=user_id,
                arbitrage_id=arb.id,
                bankroll_id=bankroll_id,
                outcome_id=outcome.id,
                bookmaker_id=bookmaker.id,
                stake_amount=stake,
                odds_at_detection=odds,
                commission_pct=commission,
                staking_method="arbitrage",
                status="pending",
            )
            db.add(bet)
            created_bets.append(bet)

            min_acceptable = (odds * (Decimal("1") - self.ODDS_TOLERANCE)).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )

            legs_out.append(
                LegInstruction(
                    bet_id=0,  # se rellena tras flush
                    bookmaker_key=bk_key,
                    bookmaker_name=bookmaker.name,
                    outcome_key=outcome_key,
                    outcome_name=leg_data.get("outcome_name", outcome_key),
                    stake_amount=stake,
                    target_odds=odds,
                    min_acceptable_odds=min_acceptable,
                    commission_pct=commission,
                )
            )

        # Reserva el capital una sola vez por el total.
        bankroll.reserved_amount = bankroll.reserved_amount + total_stake

        await db.flush()

        # Ahora que los bets tienen ID, rellenar el plan.
        for instr, bet in zip(legs_out, created_bets):
            instr.bet_id = bet.id

        await db.commit()

        expected_profit = (
            total_stake * (arb.profit_pct / Decimal("100"))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return ExecutionPlan(
            arbitrage_id=arb.id,
            match_label=match_label,
            market_type=market_type.key if market_type else "",
            total_stake=total_stake,
            currency=bankroll.currency,
            expected_profit=expected_profit,
            profit_pct=arb.profit_pct,
            legs=legs_out,
        )

    async def mark_leg_placed(
        self,
        db: AsyncSession,
        *,
        bet_id: int,
        user_id,
        odds_at_placement: Decimal,
    ) -> BetTracking:
        bet = await self._get_owned_bet(db, bet_id, user_id)
        if bet.status != "pending":
            raise ExecutionError(f"Cannot place bet in status '{bet.status}'")

        bet.status = "placed"
        bet.odds_at_placement = odds_at_placement
        bet.placed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
        return bet

    async def mark_leg_rejected(
        self,
        db: AsyncSession,
        *,
        bet_id: int,
        user_id,
        reason: str = "",
    ) -> BetTracking:
        bet = await self._get_owned_bet(db, bet_id, user_id)
        if bet.status not in ("pending", "placed"):
            raise ExecutionError(f"Cannot reject bet in status '{bet.status}'")

        # Lock del bankroll: previene race con execute/settle concurrentes que
        # pisen el reserved_amount.
        bankroll = (
            await db.execute(
                select(Bankroll).with_for_update().where(Bankroll.id == bet.bankroll_id)
            )
        ).scalar_one_or_none()
        if bankroll is not None:
            bankroll.reserved_amount = max(
                Decimal("0"), bankroll.reserved_amount - bet.stake_amount
            )

        bet.status = "rejected"
        # reason podría guardarse en un campo futuro. Por ahora sin persistencia.
        _ = reason
        await db.commit()
        return bet

    async def settle_leg(
        self,
        db: AsyncSession,
        *,
        bet_id: int,
        user_id,
        result: str,
        actual_payout: Decimal,
    ) -> BetTracking:
        """
        Liquida un bet con el resultado real del partido.

        result ∈ {won, lost, void, half_won, half_lost}. actual_payout es lo
        que el libro efectivamente paga (0 si pierde, stake si void,
        stake*odds si gana). Esperado NETO de comisiones del broker — la
        detección ya aplicó la comisión al calcular profit_pct.

        Post-condición: bet.status = "settled". Llamadas subsiguientes fallan
        para evitar doble-aplicación del PnL al bankroll.
        """
        if result not in {"won", "lost", "void", "half_won", "half_lost"}:
            raise ExecutionError(f"Invalid result '{result}'")

        bet = await self._get_owned_bet(db, bet_id, user_id)
        # Bloqueo explícito de doble-settle: si ya se liquidó, ningún reintento
        # debe sumar PnL de nuevo al bankroll.
        if bet.status == "settled":
            raise ExecutionError(f"Bet {bet_id} already settled")
        if bet.status not in ("placed", "confirmed"):
            raise ExecutionError(f"Cannot settle bet in status '{bet.status}'")

        # Lock del bankroll: elimina race con otras ops concurrentes.
        bankroll = (
            await db.execute(
                select(Bankroll).with_for_update().where(Bankroll.id == bet.bankroll_id)
            )
        ).scalar_one_or_none()

        pnl = actual_payout - bet.stake_amount

        bet.result = result
        bet.actual_payout = actual_payout
        bet.profit_loss = pnl
        bet.settled_at = datetime.now(timezone.utc).replace(tzinfo=None)
        # Transición terminal: el check al inicio del método depende de esto.
        bet.status = "settled"

        if bankroll is not None:
            bankroll.reserved_amount = max(
                Decimal("0"), bankroll.reserved_amount - bet.stake_amount
            )
            bankroll.current_amount = bankroll.current_amount + pnl

        await db.commit()
        return bet

    async def compute_exposure(
        self,
        db: AsyncSession,
        *,
        arbitrage_id: int,
        user_id,
        replacement_max_age_minutes: int = 30,
    ) -> ExposureSummary:
        """
        Calcula P&L por escenario para los legs ya placed, detecta partial fill,
        y sugiere bookmakers alternativos para los legs rejected.

        Regla del P&L por leg placed:
          Si leg.outcome gana: +stake * (odds_placement - 1) * (1 - commission)
          Si leg.outcome pierde: -stake
        Legs pending/rejected no contribuyen al P&L actual (no hay dinero puesto).
        """
        arb = await db.get(ArbitrageOpportunity, arbitrage_id)
        if arb is None:
            raise ExecutionError(f"Arbitrage {arbitrage_id} not found")

        bets = (
            await db.execute(
                select(BetTracking)
                .options(selectinload(BetTracking.bookmaker).selectinload(Bookmaker.broker))
                .where(
                    BetTracking.arbitrage_id == arbitrage_id,
                    BetTracking.user_id == user_id,
                )
            )
        ).scalars().all()

        # Outcomes del mercado — define el espacio de escenarios posibles.
        outcomes = (
            await db.execute(
                select(Outcome).where(Outcome.market_id == arb.market_id)
            )
        ).scalars().all()
        outcome_by_id = {o.id: o for o in outcomes}

        # Moneda: asumimos todos los legs del mismo arb comparten bankroll.
        currency = ""
        if bets:
            bankroll = await db.get(Bankroll, bets[0].bankroll_id)
            if bankroll is not None:
                currency = bankroll.currency

        leg_summaries: list[LegSummary] = []
        placed_by_outcome: dict[int, BetTracking] = {}
        total_placed_stake = Decimal("0")
        any_rejected = False
        any_placed = False
        any_pending = False

        for bet in bets:
            if bet.status in ("placed", "confirmed"):
                any_placed = True
                placed_by_outcome[bet.outcome_id] = bet
                total_placed_stake += bet.stake_amount
            elif bet.status == "rejected":
                any_rejected = True
            elif bet.status == "pending":
                any_pending = True

            outcome = outcome_by_id.get(bet.outcome_id)
            odds_used: Decimal | None = (
                bet.odds_at_placement
                if bet.odds_at_placement is not None
                else bet.odds_at_detection
            )
            leg_summaries.append(
                LegSummary(
                    bet_id=bet.id,
                    outcome_key=outcome.key if outcome else "",
                    outcome_name=outcome.name if outcome else "",
                    bookmaker_key=bet.bookmaker.key,
                    bookmaker_name=bet.bookmaker.name,
                    stake_amount=bet.stake_amount,
                    status=bet.status,
                    odds_effective=odds_used,
                    commission_pct=bet.commission_pct,
                )
            )

        # P&L por escenario: un outcome wins a la vez.
        scenarios: list[OutcomeScenario] = []
        for outcome in outcomes:
            pnl = Decimal("0")
            for bet in placed_by_outcome.values():
                odds = bet.odds_at_placement or bet.odds_at_detection or Decimal("0")
                if bet.outcome_id == outcome.id:
                    # Leg ganador: paga (odds-1) × stake × (1 − comisión)
                    pnl += bet.stake_amount * (odds - Decimal("1")) * (
                        Decimal("1") - (bet.commission_pct or Decimal("0"))
                    )
                else:
                    # Leg perdedor: se pierde el stake completo.
                    pnl -= bet.stake_amount
            scenarios.append(
                OutcomeScenario(
                    outcome_key=outcome.key,
                    outcome_name=outcome.name,
                    pnl=pnl.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    covered=outcome.id in placed_by_outcome,
                )
            )

        worst = min((s.pnl for s in scenarios), default=Decimal("0"))
        best = max((s.pnl for s in scenarios), default=Decimal("0"))

        # Partial fill: hay legs placed Y legs rejected simultáneamente.
        is_partial_fill = any_placed and any_rejected

        # All placed: todos los N legs del arb original están placed o confirmed.
        expected_leg_count = len(arb.legs) if arb.legs else 0
        placed_count = len(placed_by_outcome)
        all_placed = expected_leg_count > 0 and placed_count == expected_leg_count

        # Sugerencias de reemplazo para legs rejected (solo si hay partial fill).
        suggestions: list[ReplacementSuggestion] = []
        if is_partial_fill:
            suggestions = await self._find_replacement_suggestions(
                db,
                bets=bets,
                outcomes=outcome_by_id,
                max_age_minutes=replacement_max_age_minutes,
            )

        return ExposureSummary(
            arbitrage_id=arbitrage_id,
            currency=currency,
            is_partial_fill=is_partial_fill,
            any_rejected=any_rejected,
            all_placed=all_placed,
            total_placed_stake=total_placed_stake.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
            worst_case_pnl=worst,
            best_case_pnl=best,
            scenarios=scenarios,
            legs=leg_summaries,
            replacement_suggestions=suggestions,
        )

    async def _find_replacement_suggestions(
        self,
        db: AsyncSession,
        *,
        bets: list[BetTracking],
        outcomes: dict[int, Outcome],
        max_age_minutes: int,
    ) -> list[ReplacementSuggestion]:
        """
        Por cada leg rejected, sugiere alternativas: otros libros con cuotas
        recientes para ese mismo outcome, excluyendo los bookmakers ya usados
        en otros legs del arb (evita sugerir el propio libro del leg rejected
        y evita sugerir el de otra pata — que generaría conflicto de cuenta).
        """
        rejected_legs = [b for b in bets if b.status == "rejected"]
        if not rejected_legs:
            return []

        used_bookmaker_ids = {b.bookmaker_id for b in bets}
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            minutes=max_age_minutes
        )

        suggestions: list[ReplacementSuggestion] = []
        for leg in rejected_legs:
            outcome = outcomes.get(leg.outcome_id)
            if outcome is None:
                continue

            # Últimas cuotas para este outcome de books no usados ya.
            rows = (
                await db.execute(
                    select(Odds, Bookmaker)
                    .join(Bookmaker, Bookmaker.id == Odds.bookmaker_id)
                    .options(selectinload(Bookmaker.broker))
                    .where(
                        Odds.outcome_id == leg.outcome_id,
                        Odds.captured_at >= cutoff,
                        ~Bookmaker.id.in_(used_bookmaker_ids),
                    )
                    .order_by(Odds.price.desc(), Odds.captured_at.desc())
                )
            ).all()

            # Dedup: una entrada por bookmaker (la mejor cuota más reciente).
            seen: set[int] = set()
            alternatives: list[ReplacementOption] = []
            for odds_row, bm in rows:
                if bm.id in seen:
                    continue
                seen.add(bm.id)
                commission = bm.commission_pct or Decimal("0")
                if commission == 0 and bm.broker is not None:
                    commission = bm.broker.default_commission_pct or Decimal("0")
                alternatives.append(
                    ReplacementOption(
                        bookmaker_key=bm.key,
                        bookmaker_name=bm.name,
                        odds=odds_row.price,
                        commission_pct=commission,
                    )
                )
                if len(alternatives) >= 3:
                    break

            suggestions.append(
                ReplacementSuggestion(
                    outcome_key=outcome.key,
                    outcome_name=outcome.name,
                    rejected_bookmaker_key=leg.bookmaker.key,
                    alternatives=alternatives,
                )
            )

        return suggestions

    async def _get_owned_bet(
        self, db: AsyncSession, bet_id: int, user_id
    ) -> BetTracking:
        bet = await db.get(BetTracking, bet_id)
        if bet is None:
            raise ExecutionError(f"Bet {bet_id} not found")
        if bet.user_id != user_id:
            raise ExecutionError(f"Bet {bet_id} not owned by user")
        return bet
