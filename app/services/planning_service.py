"""
Planificador diario de ejecución de arbs.

Dado un tope de inversión para el día y un target de profit (en %), ordena los
arbs activos por profit descendente y asigna stakes hasta alcanzar el target
o agotar el cap. Devuelve un plan con allocations + coverage + estado.

Es determinístico (greedy), no hace optimización combinatoria — para arbs con
riesgo cero, la regla óptima es "máximo stake al arb de mayor margen primero,
hasta cap/target". No usa Kelly porque Kelly en arbs sin varianza daría ∞.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.arbitrage import ArbitrageOpportunity
from app.models.market import Market, MarketType
from app.models.match import Match
from app.models.team import Team
from app.models.user import Bankroll, UserConfig


@dataclass
class AllocationSuggestion:
    arbitrage_id: int
    match_label: str
    market_type: str
    profit_pct: Decimal
    suggested_stake: Decimal
    expected_profit: Decimal
    bookmakers: list[str]


@dataclass
class DailyPlan:
    currency: str
    daily_investment_cap: Decimal
    target_pct: Decimal
    target_profit: Decimal
    max_stake_per_arb_pct: Decimal
    available_arbs: int
    allocations: list[AllocationSuggestion] = field(default_factory=list)
    total_suggested_stake: Decimal = Decimal("0")
    expected_total_profit: Decimal = Decimal("0")
    target_coverage_pct: Decimal = Decimal("0")
    status: str = "empty"  # empty | unachievable | achievable | exceeded
    recommendation: str = ""


class PlanningService:
    async def plan_daily(
        self,
        db: AsyncSession,
        *,
        user_id,
        bankroll_id: int,
        daily_investment_cap: Decimal | None = None,
        target_pct: Decimal | None = None,
        max_stake_per_arb_pct: Decimal | None = None,
    ) -> DailyPlan:
        bankroll = await db.get(Bankroll, bankroll_id)
        if bankroll is None or bankroll.user_id != user_id:
            raise ValueError("Bankroll not found or not owned by user")

        user_config = (
            await db.execute(select(UserConfig).where(UserConfig.user_id == user_id))
        ).scalar_one_or_none()

        # Resolución de defaults: query param > user config > hardcoded fallback.
        target_pct = target_pct if target_pct is not None else (
            user_config.default_daily_target_pct if user_config else Decimal("1.0")
        )
        max_per_arb_pct = max_stake_per_arb_pct if max_stake_per_arb_pct is not None else (
            user_config.default_max_stake_per_arb_pct if user_config else Decimal("15.0")
        )
        cap = (
            daily_investment_cap
            if daily_investment_cap is not None
            else bankroll.available_amount
        )
        cap = max(Decimal("0"), cap)

        target_profit = (cap * target_pct / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        max_per_arb = cap * max_per_arb_pct / Decimal("100")

        plan = DailyPlan(
            currency=bankroll.currency,
            daily_investment_cap=cap,
            target_pct=target_pct,
            target_profit=target_profit,
            max_stake_per_arb_pct=max_per_arb_pct,
            available_arbs=0,
        )

        arbs = (
            await db.execute(
                select(ArbitrageOpportunity)
                .where(ArbitrageOpportunity.status == "active")
                .order_by(ArbitrageOpportunity.profit_pct.desc())
            )
        ).scalars().all()

        plan.available_arbs = len(arbs)

        if cap <= 0 or not arbs:
            plan.status = "empty"
            plan.recommendation = (
                "Sin arbs activos para planificar." if not arbs
                else "Cap de inversión en 0."
            )
            return plan

        remaining_cap = cap
        total_expected = Decimal("0")

        for arb in arbs:
            if remaining_cap <= 0 or total_expected >= target_profit:
                break

            profit_frac = arb.profit_pct / Decimal("100")
            # Stake máximo para este arb: menor entre (tope por arb, cap restante).
            max_stake = min(max_per_arb, remaining_cap)

            # Si este arb solo bastaría para sobrepasar target, recortar al mínimo.
            # (El usuario pidió "1% diario" — no desplegar más capital innecesario).
            needed_for_target = (
                (target_profit - total_expected) / profit_frac
                if profit_frac > 0 else Decimal("0")
            )
            stake = min(max_stake, needed_for_target)
            stake = stake.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            if stake <= 0:
                continue

            expected = (stake * profit_frac).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Cargar info de display para el allocation.
            match = await db.get(Match, arb.match_id)
            market = await db.get(Market, arb.market_id)
            market_type = await db.get(MarketType, market.market_type_id) if market else None
            home = await db.get(Team, match.home_team_id) if match else None
            away = await db.get(Team, match.away_team_id) if match else None

            plan.allocations.append(
                AllocationSuggestion(
                    arbitrage_id=arb.id,
                    match_label=(
                        f"{home.canonical_name} vs {away.canonical_name}"
                        if home and away else ""
                    ),
                    market_type=market_type.key if market_type else "",
                    profit_pct=arb.profit_pct,
                    suggested_stake=stake,
                    expected_profit=expected,
                    bookmakers=sorted({leg["bookmaker"] for leg in (arb.legs or [])}),
                )
            )

            remaining_cap -= stake
            total_expected += expected

        plan.total_suggested_stake = (cap - remaining_cap).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        plan.expected_total_profit = total_expected

        if target_profit > 0:
            plan.target_coverage_pct = (
                total_expected / target_profit * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if total_expected <= 0:
            plan.status = "empty"
            plan.recommendation = (
                "Los arbs activos no cubren el cap/target configurado."
            )
        elif total_expected >= target_profit:
            plan.status = "achievable"
            plan.recommendation = (
                f"Target cubierto con {len(plan.allocations)} arb(s). "
                f"Ejecútalos en orden desde el de mayor profit_pct."
            )
        else:
            plan.status = "unachievable"
            shortfall = target_profit - total_expected
            plan.recommendation = (
                f"Hoy llegas a {plan.target_coverage_pct:.1f}% del target. "
                f"Faltan {shortfall:.2f} {bankroll.currency} para el 1% completo. "
                f"Opciones: bajar target, activar ligas opt-in (WNBA/NWSL/WSL), "
                f"o esperar al próximo refresh de cuotas."
            )

        return plan
