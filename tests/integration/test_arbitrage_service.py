"""Tests de integración para ArbitrageDetectionService (SQLite in-memory)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.models.arbitrage import ArbitrageOpportunity
from app.models.match import Match
from app.services.arbitrage_service import ArbitrageDetectionService
from app.services.odds_service import OddsIngestionService
from app.services.seed_service import seed_database


class FakeAdapter(DataSourceAdapter):
    def __init__(self, odds_data: list[RawOddsData] | None = None):
        self.odds_data = odds_data or []

    async def fetch_odds(self, sport, regions=None, markets=None):
        return self.odds_data

    async def fetch_events(self, sport):
        return []


def raw(
    home: str,
    away: str,
    bookmaker: str,
    outcomes: list[tuple[str, float]],
    commence: datetime,
) -> RawOddsData:
    return RawOddsData(
        source="test",
        sport_key="soccer_spain_la_liga",
        league_key="soccer_spain_la_liga",
        home_team=home,
        away_team=away,
        commence_time=commence,
        bookmaker=bookmaker,
        market_type="h2h",
        outcomes=[RawOutcome(name=n, price=p) for n, p in outcomes],
        external_id=f"test_{home}_{away}",
    )


async def _ingest_arbitrage_scenario(
    db: AsyncSession,
    home: str = "Arb Home",
    away: str = "Arb Away",
    commence: datetime | None = None,
) -> None:
    """
    Seed a scenario where best odds across bookmakers form a clear arb.
    Best: home=2.60 (bet365), draw=3.80 (pinnacle), away=4.20 (betfair_ex_eu)
    Sum(1/best) = 0.3846 + 0.2632 + 0.2381 = 0.886 → ~12.9% arb
    """
    if commence is None:
        commence = datetime.now(timezone.utc) + timedelta(days=1)
    await seed_database(db)

    data = [
        raw(home, away, "bet365",
            [(home, 2.60), ("Draw", 3.10), (away, 3.20)], commence),
        raw(home, away, "pinnacle",
            [(home, 2.00), ("Draw", 3.80), (away, 3.20)], commence),
        raw(home, away, "betfair_ex_eu",
            [(home, 2.00), ("Draw", 3.10), (away, 4.20)], commence),
        raw(home, away, "williamhill",
            [(home, 2.30), ("Draw", 3.40), (away, 3.60)], commence),
        raw(home, away, "unibet_eu",
            [(home, 2.10), ("Draw", 3.50), (away, 3.50)], commence),
    ]
    service = OddsIngestionService(FakeAdapter(data))
    await service.ingest_odds(
        db, sport_key="football", league_keys=["soccer_spain_la_liga"]
    )


async def _ingest_no_arb_scenario(db: AsyncSession) -> None:
    """No arbitrage: typical vigged market across 5 bookmakers."""
    commence = datetime.now(timezone.utc) + timedelta(days=1)
    await seed_database(db)
    data = [
        raw("A", "B", "bet365",
            [("A", 2.00), ("Draw", 3.30), ("B", 3.60)], commence),
        raw("A", "B", "pinnacle",
            [("A", 2.05), ("Draw", 3.25), ("B", 3.55)], commence),
        raw("A", "B", "betfair_ex_eu",
            [("A", 2.08), ("Draw", 3.35), ("B", 3.45)], commence),
        raw("A", "B", "williamhill",
            [("A", 2.02), ("Draw", 3.28), ("B", 3.58)], commence),
        raw("A", "B", "unibet_eu",
            [("A", 2.10), ("Draw", 3.20), ("B", 3.50)], commence),
    ]
    service = OddsIngestionService(FakeAdapter(data))
    await service.ingest_odds(
        db, sport_key="football", league_keys=["soccer_spain_la_liga"]
    )


class TestDetectAll:
    async def test_finds_arbitrage(self, db_session: AsyncSession):
        await _ingest_arbitrage_scenario(db_session)

        service = ArbitrageDetectionService(
            min_profit_pct=0.5, min_bookmakers=5, min_minutes_to_kickoff=15
        )
        counts, new_arbs = await service.detect_all(db_session)

        assert counts["arbs_found"] >= 1
        assert counts["errors"] == 0
        assert len(new_arbs) >= 1

        arb = new_arbs[0]
        assert arb.status == "active"
        assert float(arb.profit_pct) > 0.5
        assert float(arb.total_implied) < 1.0
        assert arb.num_outcomes == 3
        assert len(arb.legs) == 3

    async def test_legs_record_best_bookmakers(self, db_session: AsyncSession):
        await _ingest_arbitrage_scenario(db_session)

        service = ArbitrageDetectionService(min_bookmakers=5)
        _, new_arbs = await service.detect_all(db_session)

        arb = new_arbs[0]
        leg_by_bk = {leg["bookmaker"]: leg for leg in arb.legs}
        # Expected: bet365 best at home (2.60), pinnacle best at draw (3.80),
        # betfair_ex_eu best at away (4.20)
        assert "bet365" in leg_by_bk
        assert leg_by_bk["bet365"]["odds"] == 2.60
        assert "pinnacle" in leg_by_bk
        assert leg_by_bk["pinnacle"]["odds"] == 3.80
        assert "betfair_ex_eu" in leg_by_bk
        assert leg_by_bk["betfair_ex_eu"]["odds"] == 4.20

    async def test_no_arbitrage_when_market_is_vigged(self, db_session: AsyncSession):
        await _ingest_no_arb_scenario(db_session)

        service = ArbitrageDetectionService(min_bookmakers=5)
        counts, new_arbs = await service.detect_all(db_session)

        assert counts["arbs_found"] == 0
        assert new_arbs == []

        # DB should also be empty of arbs
        rows = (await db_session.execute(select(ArbitrageOpportunity))).scalars().all()
        assert rows == []

    async def test_skips_matches_too_close_to_kickoff(
        self, db_session: AsyncSession
    ):
        """min_minutes_to_kickoff filter excludes matches about to start."""
        # Commence only 5 minutes ahead → below default 15 min threshold
        soon = datetime.now(timezone.utc) + timedelta(minutes=5)
        await _ingest_arbitrage_scenario(db_session, commence=soon)

        service = ArbitrageDetectionService(
            min_bookmakers=5, min_minutes_to_kickoff=15
        )
        counts, _ = await service.detect_all(db_session)
        assert counts["arbs_found"] == 0


class TestUpsertBehavior:
    async def test_second_detection_updates_not_duplicates(
        self, db_session: AsyncSession
    ):
        await _ingest_arbitrage_scenario(db_session)
        service = ArbitrageDetectionService(min_bookmakers=5)

        await service.detect_all(db_session)
        count1 = len((await db_session.execute(select(ArbitrageOpportunity))).scalars().all())

        await service.detect_all(db_session)
        count2 = len((await db_session.execute(select(ArbitrageOpportunity))).scalars().all())

        assert count1 == count2
        assert count1 >= 1

    async def test_dead_with_same_legs_reopens_not_duplicates(
        self, db_session: AsyncSession
    ):
        """A dead arb re-detected with the same legs should reopen, not duplicate."""
        await _ingest_arbitrage_scenario(db_session)
        service = ArbitrageDetectionService(min_bookmakers=5)

        await service.detect_all(db_session)
        arb = (
            await db_session.execute(select(ArbitrageOpportunity))
        ).scalar_one()
        original_id = arb.id
        original_detected_at = arb.detected_at

        # Simulate the arb dying (e.g. one book briefly dropped its price)
        arb.status = "dead"
        arb.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db_session.flush()

        # Same odds reappear -> same legs signature -> should reopen, not insert
        await service.detect_all(db_session)
        all_arbs = (
            await db_session.execute(select(ArbitrageOpportunity))
        ).scalars().all()

        assert len(all_arbs) == 1
        assert all_arbs[0].id == original_id
        assert all_arbs[0].status == "active"
        assert all_arbs[0].closed_at is None
        assert all_arbs[0].detected_at == original_detected_at

    async def test_update_refreshes_profit_and_legs(self, db_session: AsyncSession):
        await _ingest_arbitrage_scenario(db_session)
        service = ArbitrageDetectionService(min_bookmakers=5)
        await service.detect_all(db_session)

        arb_before = (
            await db_session.execute(select(ArbitrageOpportunity).limit(1))
        ).scalar_one()
        profit_before = float(arb_before.profit_pct)

        # Tamper: mutate in-memory to ensure next run re-computes from DB
        arb_before.profit_pct = Decimal("99.999")
        await db_session.flush()

        await service.detect_all(db_session)
        await db_session.refresh(arb_before)
        assert float(arb_before.profit_pct) == profit_before


class TestLegsPointField:
    async def test_h2h_market_persists_point_as_none(
        self, db_session: AsyncSession
    ):
        await _ingest_arbitrage_scenario(db_session)
        service = ArbitrageDetectionService(min_bookmakers=5)
        _, new_arbs = await service.detect_all(db_session)

        assert len(new_arbs) >= 1
        for leg in new_arbs[0].legs:
            assert "point" in leg
            assert leg["point"] is None

    async def test_market_with_parameter_persists_point_value(
        self, db_session: AsyncSession
    ):
        from sqlalchemy import delete

        from app.models.market import Market

        await _ingest_arbitrage_scenario(db_session)

        # Inject a line into the market and clear any existing arb so the
        # next detection rebuilds legs from scratch.
        market = (await db_session.execute(select(Market))).scalars().first()
        market.parameter = Decimal("8.50")
        await db_session.execute(delete(ArbitrageOpportunity))
        await db_session.flush()

        service = ArbitrageDetectionService(min_bookmakers=5)
        _, new_arbs = await service.detect_all(db_session)

        assert len(new_arbs) >= 1
        for leg in new_arbs[0].legs:
            assert leg["point"] == 8.5


class TestExpireArbs:
    async def test_expires_past_kickoff(self, db_session: AsyncSession):
        """Arbs whose expires_at (match commence_time) is past should be expired."""
        await seed_database(db_session)

        # Ingest + detect to create an active arb
        future = datetime.now(timezone.utc) + timedelta(days=1)
        await _ingest_arbitrage_scenario(db_session, commence=future)

        service = ArbitrageDetectionService(min_bookmakers=5)
        await service.detect_all(db_session)

        # Force expires_at into the past
        arb = (await db_session.execute(select(ArbitrageOpportunity))).scalar_one()
        assert arb.status == "active"
        arb.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        await db_session.flush()

        # Also force the match into the past so detect_all won't re-detect it,
        # but will still run its _expire_arbs pass
        match = (await db_session.execute(select(Match))).scalar_one()
        match.commence_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        await db_session.flush()

        counts, _ = await service.detect_all(db_session)

        assert counts.get("expired", 0) >= 1
        await db_session.refresh(arb)
        assert arb.status == "expired"
        assert arb.closed_at is not None

    async def test_does_not_expire_active_future_arbs(
        self, db_session: AsyncSession
    ):
        await _ingest_arbitrage_scenario(db_session)
        service = ArbitrageDetectionService(min_bookmakers=5)
        await service.detect_all(db_session)

        # Run again — should not expire because expires_at is in the future
        counts, _ = await service.detect_all(db_session)
        assert counts.get("expired", 0) == 0

        arb = (await db_session.execute(select(ArbitrageOpportunity))).scalar_one()
        assert arb.status == "active"


class TestMarketsScannedCounter:
    async def test_counts_markets_actually_scanned(self, db_session: AsyncSession):
        await _ingest_arbitrage_scenario(db_session)
        service = ArbitrageDetectionService(min_bookmakers=5)
        counts, _ = await service.detect_all(db_session)
        # At least 1 market (h2h) was scanned
        assert counts["markets_scanned"] >= 1

    async def test_zero_when_no_eligible_matches(self, db_session: AsyncSession):
        await seed_database(db_session)  # no matches ingested
        service = ArbitrageDetectionService(min_bookmakers=5)
        counts, _ = await service.detect_all(db_session)
        assert counts["markets_scanned"] == 0


class TestStaleOddsFilter:
    async def test_ignores_odds_older_than_cutoff(self, db_session: AsyncSession):
        """Stale odds must not contribute to arbitrage detection."""
        from app.models.market import Odds

        await _ingest_arbitrage_scenario(db_session)

        # Age all odds beyond the 30-min default window
        stale_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
        rows = (await db_session.execute(select(Odds))).scalars().all()
        for row in rows:
            row.captured_at = stale_ts
        await db_session.flush()

        service = ArbitrageDetectionService(min_bookmakers=5)
        counts, new_arbs = await service.detect_all(db_session)
        assert counts["arbs_found"] == 0
        assert new_arbs == []

    async def test_configurable_window_accepts_older_odds(
        self, db_session: AsyncSession
    ):
        """Raising max_odds_age_minutes lets older odds back in."""
        from app.models.market import Odds

        await _ingest_arbitrage_scenario(db_session)

        # 45 min old — stale for default (30), fresh for 120
        stale_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=45)
        rows = (await db_session.execute(select(Odds))).scalars().all()
        for row in rows:
            row.captured_at = stale_ts
        await db_session.flush()

        default_svc = ArbitrageDetectionService(min_bookmakers=5)
        counts, _ = await default_svc.detect_all(db_session)
        assert counts["arbs_found"] == 0

        # Clean up arbs persisted from the first run so the second run sees a blank slate
        for arb in (await db_session.execute(select(ArbitrageOpportunity))).scalars().all():
            await db_session.delete(arb)
        await db_session.flush()

        loose_svc = ArbitrageDetectionService(min_bookmakers=5, max_odds_age_minutes=120)
        counts, _ = await loose_svc.detect_all(db_session)
        assert counts["arbs_found"] >= 1


class TestMinBookmakersConfig:
    async def test_respects_configured_min_bookmakers(self, db_session: AsyncSession):
        # Ingest only 3 bookmakers → below service default min_bookmakers=5
        commence = datetime.now(timezone.utc) + timedelta(days=1)
        await seed_database(db_session)
        data = [
            raw("X", "Y", "bet365",
                [("X", 2.60), ("Draw", 3.10), ("Y", 3.20)], commence),
            raw("X", "Y", "pinnacle",
                [("X", 2.00), ("Draw", 3.80), ("Y", 3.20)], commence),
            raw("X", "Y", "betfair_ex_eu",
                [("X", 2.00), ("Draw", 3.10), ("Y", 4.20)], commence),
        ]
        svc = OddsIngestionService(FakeAdapter(data))
        await svc.ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_spain_la_liga"]
        )

        # Service with default min_bookmakers=5 → skipped
        strict = ArbitrageDetectionService(min_bookmakers=5)
        counts, _ = await strict.detect_all(db_session)
        assert counts["arbs_found"] == 0

        # Relaxed service (min_bookmakers=3) → arb detected
        loose = ArbitrageDetectionService(min_bookmakers=3)
        counts, _ = await loose.detect_all(db_session)
        assert counts["arbs_found"] >= 1


class TestSuspendedOddsFilter:
    """
    Reproduce el patrón del falso positivo del arb #80 (Hawks/Knicks, abr 2026):
    un bookmaker con un outcome a 25.0 y el outcome opuesto a 1.00 (línea
    suspendida). El detector solía tomar la cuota de 25.0 como "mejor" sin
    notar que el mismo libro tiene el otro lado congelado, generando arbs
    fantasma de 2 dígitos.
    """

    async def test_skips_bookmaker_with_suspended_leg(
        self, db_session: AsyncSession
    ):
        commence = datetime.now(timezone.utc) + timedelta(days=1)
        await seed_database(db_session)

        # 5 libros con cuotas normales (vig saludable, sin arb real entre ellos).
        normal_books = [
            raw("X", "Y", "bet365",
                [("X", 2.00), ("Draw", 3.30), ("Y", 3.60)], commence),
            raw("X", "Y", "pinnacle",
                [("X", 2.05), ("Draw", 3.25), ("Y", 3.55)], commence),
            raw("X", "Y", "betfair_ex_eu",
                [("X", 2.08), ("Draw", 3.35), ("Y", 3.45)], commence),
            raw("X", "Y", "williamhill",
                [("X", 2.02), ("Draw", 3.28), ("Y", 3.58)], commence),
            raw("X", "Y", "unibet_eu",
                [("X", 2.10), ("Draw", 3.20), ("Y", 3.50)], commence),
        ]
        # Libro con mercado suspendido: home superalto, draw/away a 1.00.
        # Sin filtro: best X = 25.0 (ese libro) → arb falso de ~50% profit.
        suspended_book = raw(
            "X", "Y", "betsson",
            [("X", 25.00), ("Draw", 1.00), ("Y", 1.00)],
            commence,
        )
        service = OddsIngestionService(FakeAdapter(normal_books + [suspended_book]))
        await service.ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_spain_la_liga"]
        )

        svc = ArbitrageDetectionService(min_bookmakers=5)
        counts, new_arbs = await svc.detect_all(db_session)
        assert counts["arbs_found"] == 0, (
            "Libro con outcome ≤ 1.05 debe quedar fuera; sin filtro habría arb falso"
        )
        assert new_arbs == []

    async def test_revalidate_marks_dead_when_book_market_freezes(
        self, db_session: AsyncSession
    ):
        """
        Si un arb se detectó cuando todos los libros estaban sanos y luego un
        libro suspende su mercado (cualquier outcome ≤ 1.05), la revalidación
        debe clasificar el arb como dead — el leg de 25.0 no es ejecutable.
        """
        from datetime import datetime as _dt
        from app.models.bookmaker import Bookmaker
        from app.models.market import Odds, Outcome

        commence = datetime.now(timezone.utc) + timedelta(days=1)
        await _ingest_arbitrage_scenario(
            db_session, home="Sus Home", away="Sus Away", commence=commence
        )

        svc = ArbitrageDetectionService(min_bookmakers=5)
        _, new_arbs = await svc.detect_all(db_session)
        assert len(new_arbs) >= 1
        arb = new_arbs[0]
        await db_session.commit()

        # Inyecta cuota suspendida directamente: un libro del arb cuelga otro
        # outcome del mismo mercado a 1.00.
        target_bk_key = arb.legs[0]["bookmaker"]
        target_outcome_key = arb.legs[1]["outcome"]
        bk = (await db_session.execute(
            select(Bookmaker).where(Bookmaker.key == target_bk_key)
        )).scalar_one()
        outcome = (await db_session.execute(
            select(Outcome).where(
                Outcome.market_id == arb.market_id,
                Outcome.key == target_outcome_key,
            )
        )).scalar_one()
        db_session.add(Odds(
            outcome_id=outcome.id,
            bookmaker_id=bk.id,
            price=Decimal("1.00"),
            captured_at=_dt.utcnow(),
            source="test",
        ))
        await db_session.commit()

        result = await svc.revalidate_arb(db_session, arb.id)
        assert result.status == "dead", (
            f"esperado dead por suspensión, fue {result.status}"
        )

    async def test_revalidate_marks_dead_when_leg_odds_at_suspended_threshold(
        self, db_session: AsyncSession
    ):
        """Cuotas en (1.0, 1.05] sobre el leg propio del arb deben marcarse dead.

        Antes el filtro era `<= 1.0`, dejando pasar 1.01-1.05 que son la firma
        de un mercado parcialmente suspendido por el libro. Ahora consistente
        con el threshold a nivel de mercado.
        """
        from datetime import datetime as _dt
        from app.models.bookmaker import Bookmaker
        from app.models.market import Odds, Outcome

        commence = datetime.now(timezone.utc) + timedelta(days=1)
        await _ingest_arbitrage_scenario(
            db_session, home="Edge Home", away="Edge Away", commence=commence
        )

        svc = ArbitrageDetectionService(min_bookmakers=5)
        _, new_arbs = await svc.detect_all(db_session)
        assert len(new_arbs) >= 1
        arb = new_arbs[0]
        await db_session.commit()

        # Bajar la cuota del propio leg del arb a 1.03 (en zona suspendida).
        target_leg = arb.legs[0]
        bk = (await db_session.execute(
            select(Bookmaker).where(Bookmaker.key == target_leg["bookmaker"])
        )).scalar_one()
        outcome = (await db_session.execute(
            select(Outcome).where(
                Outcome.market_id == arb.market_id,
                Outcome.key == target_leg["outcome"],
            )
        )).scalar_one()
        db_session.add(Odds(
            outcome_id=outcome.id,
            bookmaker_id=bk.id,
            price=Decimal("1.03"),
            captured_at=_dt.utcnow(),
            source="test",
        ))
        await db_session.commit()

        result = await svc.revalidate_arb(db_session, arb.id)
        assert result.status == "dead"
