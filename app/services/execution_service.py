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
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.arbitrage import ArbitrageOpportunity
from app.models.bookmaker import Bookmaker
from app.models.market import Market, MarketType, Outcome
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

        bankroll = await db.get(Bankroll, bankroll_id)
        if bankroll is None or bankroll.user_id != user_id:
            raise ExecutionError("Bankroll not found or not owned by user")
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

        # Libera capital reservado de este leg específico.
        bankroll = await db.get(Bankroll, bet.bankroll_id)
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
        result ∈ {won, lost, void, half_won, half_lost}. actual_payout es lo que
        el libro efectivamente paga (0 si pierde, stake si void, stake*odds si gana).
        """
        if result not in {"won", "lost", "void", "half_won", "half_lost"}:
            raise ExecutionError(f"Invalid result '{result}'")

        bet = await self._get_owned_bet(db, bet_id, user_id)
        if bet.status not in ("placed", "confirmed"):
            raise ExecutionError(f"Cannot settle bet in status '{bet.status}'")

        pnl = actual_payout - bet.stake_amount

        bet.result = result
        bet.actual_payout = actual_payout
        bet.profit_loss = pnl
        bet.settled_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # Libera reserve y ajusta current_amount con el PnL neto.
        bankroll = await db.get(Bankroll, bet.bankroll_id)
        if bankroll is not None:
            bankroll.reserved_amount = max(
                Decimal("0"), bankroll.reserved_amount - bet.stake_amount
            )
            bankroll.current_amount = bankroll.current_amount + pnl

        await db.commit()
        return bet

    async def _get_owned_bet(
        self, db: AsyncSession, bet_id: int, user_id
    ) -> BetTracking:
        bet = await db.get(BetTracking, bet_id)
        if bet is None:
            raise ExecutionError(f"Bet {bet_id} not found")
        if bet.user_id != user_id:
            raise ExecutionError(f"Bet {bet_id} not owned by user")
        return bet
