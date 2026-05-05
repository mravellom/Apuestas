"""Servicio de detección de arbitraje: busca surebets entre bookmakers."""

import logging
from dataclasses import dataclass
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

# Cuotas ≤ este umbral indican que el bookmaker tiene el mercado SUSPENDIDO
# (placeholder ~1.00). Usar la "otra pata" del mismo libro produce arbs falsos
# de 2 dígitos (ver caso Hawks/Knicks #80). Si CUALQUIER outcome del mercado
# del libro está bajo este umbral, el libro entero queda fuera.
SUSPENDED_ODDS_THRESHOLD = 1.05


@dataclass
class RevalidationResult:
    """
    Resultado de re-evaluar un arb activo contra las cuotas más recientes en DB.

    status:
      alive — profit_pct actual ≥ 80% del detectado (ejecutable con confianza)
      stale — profit_pct entre 50% y 80% del detectado (requiere confirmación
              explícita del usuario para ejecutar)
      dead  — total_implied ≥ 1.0 o profit_pct cae debajo de 50% del detectado;
              no tiene sentido ejecutar

    age_seconds es cuánto tiempo ha pasado desde que el arb fue detectado.
    """
    status: str  # alive | stale | dead
    detected_profit_pct: float
    current_profit_pct: float
    age_seconds: int
    current_legs: list[dict] | None = None

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

    async def revalidate_arb(
        self, db: AsyncSession, arb_id: int
    ) -> RevalidationResult:
        """
        Re-evalúa un arb EXACTAMENTE con los mismos legs originales (mismos
        bookmakers, mismos outcomes) contra las últimas cuotas en DB.

        Semántica: "¿Sigue siendo ejecutable ESTE arb específico?"
          - Si un bookmaker dejó de cotizar ese outcome o su última cuota es
            muy vieja (> max_odds_age_minutes), el leg no se puede reprecear
            y el arb se clasifica DEAD.
          - Si todos los legs tienen cuotas frescas, se recalcula profit_pct
            con las cuotas actuales del mismo set de (book, outcome) y se
            compara contra el detected_profit_pct original.

        Esta es la corrección del bug #5. Antes hacíamos una re-detección
        completa del market (`_detect` con min_bookmakers=1, min_profit_pct=0)
        que podía retornar un arb distinto al original — ej. con otro libro
        que inesperadamente aparecía con mejor cuota. Eso era confuso porque
        la "revalidación" devolvía legs que el usuario nunca detectó. Ahora
        reprecea los mismos legs sin sustituir libros.
        """
        arb = await db.get(ArbitrageOpportunity, arb_id)
        if arb is None:
            raise ValueError(f"Arbitrage {arb_id} not found")

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        age_seconds = int((now - arb.detected_at).total_seconds())
        detected_pct = float(arb.profit_pct)

        if not arb.legs:
            return RevalidationResult(
                status="dead",
                detected_profit_pct=detected_pct,
                current_profit_pct=0.0,
                age_seconds=age_seconds,
            )

        # Carga los outcomes del market para mapear bookmaker_key + outcome_key
        # → outcome_id. Necesitamos esos IDs para buscar odds específicos.
        outcomes = (
            await db.execute(select(Outcome).where(Outcome.market_id == arb.market_id))
        ).scalars().all()
        outcomes_by_key = {o.key: o for o in outcomes}

        # Verifica que los outcomes referenciados en arb.legs sigan existiendo.
        for leg in arb.legs:
            if leg["outcome"] not in outcomes_by_key:
                return RevalidationResult(
                    status="dead",
                    detected_profit_pct=detected_pct,
                    current_profit_pct=0.0,
                    age_seconds=age_seconds,
                )

        # Carga bookmakers activos referenciados en los legs, con broker eager
        # para resolver comisión.
        bk_keys = {leg["bookmaker"] for leg in arb.legs}
        bk_rows = (
            await db.execute(
                select(Bookmaker)
                .options(selectinload(Bookmaker.broker))
                .where(Bookmaker.key.in_(bk_keys), Bookmaker.active.is_(True))
            )
        ).scalars().all()
        bk_map = {b.key: b for b in bk_rows}

        # Si algún bookmaker del arb original fue marcado inactivo, el arb
        # no es ejecutable con la config actual — dead.
        if len(bk_map) != len(bk_keys):
            return RevalidationResult(
                status="dead",
                detected_profit_pct=detected_pct,
                current_profit_pct=0.0,
                age_seconds=age_seconds,
            )

        cutoff = now - timedelta(minutes=self.max_odds_age_minutes)

        # Si cualquier libro del arb tiene CUALQUIER outcome del mercado en
        # cuota suspendida (≤ SUSPENDED_ODDS_THRESHOLD), su mercado está
        # congelado: el leg que parecía sano (ej. 25.0) no es ejecutable.
        # Cuota 1.00 en el outcome opuesto es la firma del falso positivo.
        bk_ids_in_arb = [b.id for b in bk_map.values()]
        out_ids = [o.id for o in outcomes]
        suspension_rows = (
            await db.execute(
                select(Odds.outcome_id, Odds.bookmaker_id, Odds.price)
                .where(
                    Odds.outcome_id.in_(out_ids),
                    Odds.bookmaker_id.in_(bk_ids_in_arb),
                    Odds.captured_at >= cutoff,
                )
                .order_by(Odds.captured_at.desc())
            )
        ).all()
        seen_pairs: set[tuple[int, int]] = set()
        for out_id, bk_id, price in suspension_rows:
            pair = (out_id, bk_id)
            if pair in seen_pairs:
                continue  # solo la más reciente
            seen_pairs.add(pair)
            if float(price) <= SUSPENDED_ODDS_THRESHOLD:
                return RevalidationResult(
                    status="dead",
                    detected_profit_pct=detected_pct,
                    current_profit_pct=0.0,
                    age_seconds=age_seconds,
                )

        # Re-precea cada leg con su última cuota específica.
        market = await db.get(Market, arb.market_id)
        point = (
            float(market.parameter)
            if market is not None and market.parameter is not None
            else None
        )
        repriced: list[dict] = []
        effective_implied_sum = 0.0

        for leg in arb.legs:
            outcome = outcomes_by_key[leg["outcome"]]
            bookmaker = bk_map[leg["bookmaker"]]

            latest_odds = (
                await db.execute(
                    select(Odds.price)
                    .where(
                        Odds.outcome_id == outcome.id,
                        Odds.bookmaker_id == bookmaker.id,
                        Odds.captured_at >= cutoff,
                    )
                    .order_by(Odds.captured_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if latest_odds is None or float(latest_odds) <= 1.0:
                # Ese leg no tiene cuota fresca — arb no es ejecutable.
                return RevalidationResult(
                    status="dead",
                    detected_profit_pct=detected_pct,
                    current_profit_pct=0.0,
                    age_seconds=age_seconds,
                )

            odds_f = float(latest_odds)
            # Comisión efectiva: book o broker.
            commission = float(bookmaker.commission_pct or 0)
            if commission == 0 and bookmaker.broker is not None:
                commission = float(bookmaker.broker.default_commission_pct or 0)

            eff_odds = 1.0 + (odds_f - 1.0) * (1.0 - commission)
            effective_implied_sum += 1.0 / eff_odds

            repriced.append({
                "outcome": leg["outcome"],
                "outcome_name": leg.get("outcome_name", leg["outcome"]),
                "bookmaker": leg["bookmaker"],
                "odds": odds_f,
                "stake_pct": (1.0 / eff_odds),  # se normaliza abajo
                "point": point,
            })

        if effective_implied_sum >= 1.0:
            # Suma de probabilidades implícitas >= 1 → no hay arb. Dead.
            return RevalidationResult(
                status="dead",
                detected_profit_pct=detected_pct,
                current_profit_pct=0.0,
                age_seconds=age_seconds,
            )

        current_pct = (1.0 / effective_implied_sum - 1.0) * 100.0

        # Normaliza stake_pct para que sumen 1 (con absorción del residuo en
        # el último leg — ver fix de bug #7 en detect_arbitrage).
        for leg_d in repriced:
            leg_d["stake_pct"] = leg_d["stake_pct"] / effective_implied_sum
        residual = 1.0 - sum(leg_d["stake_pct"] for leg_d in repriced)
        repriced[-1]["stake_pct"] += residual

        # Clasificación relativa al profit original detectado.
        ratio = current_pct / detected_pct if detected_pct > 0 else 0
        if ratio >= 0.8:
            status = "alive"
        elif ratio >= 0.5:
            status = "stale"
        else:
            status = "dead"

        return RevalidationResult(
            status=status,
            detected_profit_pct=detected_pct,
            current_profit_pct=current_pct,
            age_seconds=age_seconds,
            current_legs=repriced,
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
            # Excluye bookmakers marcados inactivos (p.ej. libros fantasma
            # creados por auto-create antes del fix de bug #4, o books con
            # comisión desconocida deshabilitados manualmente).
            .where(Bookmaker.active.is_(True))
        )

        bookmaker_odds: dict[str, dict[int, float]] = {}
        for odds, bookmaker in result.all():
            if bookmaker.key not in bookmaker_odds:
                bookmaker_odds[bookmaker.key] = {}
            bookmaker_odds[bookmaker.key][odds.outcome_id] = float(odds.price)

        odds_by_bookmaker: dict[str, list[float]] = {}
        for bk_key, odds_map in bookmaker_odds.items():
            if not all(o.id in odds_map for o in outcomes):
                continue
            odds_list = [odds_map[o.id] for o in outcomes]
            # Si cualquier outcome está suspendido, el mercado del libro está
            # congelado: descartar el libro entero.
            if any(p <= SUSPENDED_ODDS_THRESHOLD for p in odds_list):
                continue
            odds_by_bookmaker[bk_key] = odds_list

        return odds_by_bookmaker

    REOPEN_WINDOW_HOURS = 6

    async def _save_arb(
        self,
        db: AsyncSession,
        arb: ArbOpportunity,
        market: Market,
        match: Match,
    ) -> ArbitrageOpportunity | None:
        point = float(market.parameter) if market.parameter is not None else None
        legs_data = [
            {
                "outcome": leg.outcome_key,
                "outcome_name": leg.outcome_name,
                "bookmaker": leg.bookmaker_key,
                "odds": leg.best_odds,
                "stake_pct": leg.stake_pct,
                "point": point,
            }
            for leg in arb.legs
        ]

        # Active arb for the same market is always an upsert target.
        active = (
            await db.execute(
                select(ArbitrageOpportunity).where(
                    ArbitrageOpportunity.match_id == match.id,
                    ArbitrageOpportunity.market_id == market.id,
                    ArbitrageOpportunity.status == "active",
                )
            )
        ).scalar_one_or_none()

        if active:
            active.total_implied = Decimal(str(arb.total_implied))
            active.profit_pct = Decimal(str(arb.profit_pct))
            active.legs = legs_data
            return None

        # No active arb: try to reopen a recent dead one with the same legs
        # signature (same bookmaker+outcome set), so we don't create a duplicate
        # row each time the market oscillates in and out of arb territory.
        new_signature = frozenset(
            (leg.bookmaker_key, leg.outcome_key) for leg in arb.legs
        )
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            hours=self.REOPEN_WINDOW_HOURS
        )
        recent_dead = (
            await db.execute(
                select(ArbitrageOpportunity)
                .where(
                    ArbitrageOpportunity.match_id == match.id,
                    ArbitrageOpportunity.market_id == market.id,
                    ArbitrageOpportunity.status == "dead",
                    ArbitrageOpportunity.closed_at >= cutoff,
                )
                .order_by(ArbitrageOpportunity.closed_at.desc())
            )
        ).scalars().all()

        for candidate in recent_dead:
            cand_signature = frozenset(
                (leg.get("bookmaker"), leg.get("outcome"))
                for leg in (candidate.legs or [])
            )
            if cand_signature == new_signature:
                candidate.status = "active"
                candidate.closed_at = None
                candidate.total_implied = Decimal(str(arb.total_implied))
                candidate.profit_pct = Decimal(str(arb.profit_pct))
                candidate.legs = legs_data
                return None

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

    async def sweep_dead_arbs(self, db: AsyncSession) -> int:
        """
        Revalida cada arb `active` con kickoff aún en el futuro y persiste
        `status='dead'` cuando la revalidación así lo indica.

        Cierra la brecha entre `_expire_arbs` (que solo vence por kickoff) y
        `revalidate_arb` (read-only): opps que siguen pre-kickoff pero cuyas
        cuotas ya no forman arb quedan como zombies en DB y se filtran por
        `?status=active`. Este sweep las marca `dead` explícitamente.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        rows = (
            await db.execute(
                select(ArbitrageOpportunity.id).where(
                    ArbitrageOpportunity.status == "active",
                    ArbitrageOpportunity.expires_at > now,
                )
            )
        ).scalars().all()

        killed = 0
        for arb_id in rows:
            try:
                result = await self.revalidate_arb(db, arb_id)
            except ValueError:
                continue
            if result.status == "dead":
                arb = await db.get(ArbitrageOpportunity, arb_id)
                if arb is not None and arb.status == "active":
                    arb.status = "dead"
                    arb.closed_at = now
                    killed += 1

        if killed:
            await db.commit()
        return killed
