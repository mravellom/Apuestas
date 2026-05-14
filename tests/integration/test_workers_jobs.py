"""Tests para los jobs del scheduler (workers/jobs.py).

Los jobs usan `async_session` a nivel de módulo (no el fixture de DI). Para
poder testearlos contra la DB in-memory, patcheamos `app.workers.jobs.async_session`
a un sessionmaker que apunta al engine del fixture `db_engine`.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.models.alert import AlertConfig
from app.models.arbitrage import ArbitrageOpportunity
from app.models.bookmaker import Bookmaker
from app.models.market import ClosingLine, Odds, Outcome
from app.models.match import Match
from app.models.opportunity import Opportunity
from app.models.paper import PaperBet
from app.models.user import User, UserConfig
from app.services.auth_service import hash_password
from app.services.odds_service import OddsIngestionService
from app.services.seed_service import seed_database
from app.workers import jobs as jobs_module


class FakeAdapter(DataSourceAdapter):
    def __init__(self, odds_data=None):
        self.odds_data = odds_data or []
        self.closed = False

    async def fetch_odds(self, sport, regions=None, markets=None):
        return self.odds_data

    async def fetch_events(self, sport):
        return []

    async def close(self):
        self.closed = True


def _raw(home, away, bk, outcomes, commence, league="soccer_spain_la_liga"):
    return RawOddsData(
        source="test",
        sport_key=league,
        league_key=league,
        home_team=home,
        away_team=away,
        commence_time=commence,
        bookmaker=bk,
        market_type="h2h",
        outcomes=[RawOutcome(name=n, price=p) for n, p in outcomes],
        external_id=f"job_test_{home}_{away}_{bk}",
    )


@pytest.fixture
def patch_async_session(db_engine, monkeypatch):
    """Redirige jobs.async_session a la DB del fixture."""
    test_sessionmaker = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(jobs_module, "async_session", test_sessionmaker)
    return test_sessionmaker


async def _make_user_with_alert(db: AsyncSession, dest: str = "chat-1") -> None:
    import uuid
    user = User(
        id=uuid.uuid4(),
        email=f"{dest}@test.com",
        username=dest,
        hashed_password=hash_password("x" * 10),
        role="premium",
    )
    db.add(user)
    db.add(UserConfig(user_id=user.id))
    await db.flush()
    db.add(
        AlertConfig(
            user_id=user.id,
            channel="telegram",
            destination=dest,
            min_value_pct=Decimal("0.0"),
            active=True,
        )
    )
    await db.commit()


class TestFetchOddsJob:
    pass  # throttle ahora se persiste en api_usage_log; cada test
    # usa una DB limpia (db_session fixture) por lo que no hay state cross-test
    # que limpiar a nivel de módulo.

    async def test_skips_when_no_api_key(
        self, patch_async_session, db_session, monkeypatch, caplog
    ):
        """Sin ODDS_API_KEY, el job no debe llamar al adapter."""
        import logging
        from app.config import settings

        monkeypatch.setattr(settings, "ODDS_API_KEY", "")
        with caplog.at_level(logging.WARNING, logger="app.workers.jobs"):
            await jobs_module.fetch_odds_job()
        assert any("ODDS_API_KEY" in rec.message for rec in caplog.records)

    def test_required_interval_thresholds(self):
        """_required_interval_seconds mapea proximity → cadencia correcta."""
        from app.config import settings

        assert (
            jobs_module._required_interval_seconds(2.5)
            == settings.FETCH_ODDS_INTERVAL_NEAR_SECONDS
        )
        assert (
            jobs_module._required_interval_seconds(8.0)
            == settings.FETCH_ODDS_INTERVAL_MID_SECONDS
        )
        assert (
            jobs_module._required_interval_seconds(20.0)
            == settings.FETCH_ODDS_INTERVAL_FAR_SECONDS
        )
        assert (
            jobs_module._required_interval_seconds(None)
            == settings.FETCH_ODDS_INTERVAL_FAR_SECONDS
        )

    async def test_throttles_when_last_fetch_recent(
        self, patch_async_session, db_session, monkeypatch, caplog
    ):
        """Si el último fetch persistido es reciente, el job se salta."""
        import logging
        from app.config import settings
        from app.adapters.odds_api import OddsAPIAdapter
        from app.models.api_usage import ApiUsageLog

        monkeypatch.setattr(settings, "ODDS_API_KEY", "fake-key")
        await seed_database(db_session)

        # Persistimos un fetch hecho hace 60s — bajo el NEAR de 300s.
        recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=60)
        db_session.add(ApiUsageLog(
            source=OddsAPIAdapter.SOURCE,
            sport_key="football",
            endpoint="odds",
            requests_remaining=10000,
            requests_used=100,
            captured_at=recent,
        ))
        await db_session.commit()

        # Match a 1h del kickoff para forzar bucket NEAR.
        commence = datetime.now(timezone.utc) + timedelta(hours=1)
        data = [
            _raw("TH", "TA", "bet365",
                 [("TH", 2.10), ("Draw", 3.30), ("TA", 3.60)], commence,
                 league="soccer_epl"),
        ]
        await OddsIngestionService(FakeAdapter(data)).ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_epl"]
        )

        # Si llegara al adapter, este boom haría fallar el test.
        class BoomAdapter(FakeAdapter):
            async def fetch_odds(self, *a, **kw):
                raise AssertionError("adapter must not be called when throttled")

        monkeypatch.setattr(
            jobs_module, "OddsAPIAdapter", lambda *a, **kw: BoomAdapter()
        )

        with caplog.at_level(logging.INFO, logger="app.workers.jobs"):
            await jobs_module.fetch_odds_job()
        assert any("Fetch throttled" in r.message for r in caplog.records)

    async def test_invokes_adapter_and_persists(
        self, patch_async_session, db_session, monkeypatch
    ):
        """Con API key y datos → ingesta y persiste matches/odds."""
        from app.config import settings
        monkeypatch.setattr(settings, "ODDS_API_KEY", "fake-key")

        await seed_database(db_session)

        commence = datetime.now(timezone.utc) + timedelta(days=1)
        fake_data = [
            _raw("H1", "A1", "bet365",
                 [("H1", 2.10), ("Draw", 3.30), ("A1", 3.60)], commence,
                 league="soccer_epl"),
        ]
        fake_adapter = FakeAdapter(fake_data)

        # Patch adapter constructor to return our fake
        monkeypatch.setattr(
            jobs_module, "OddsAPIAdapter", lambda *a, **kw: fake_adapter
        )

        await jobs_module.fetch_odds_job()

        # Match persisted
        matches = (await db_session.execute(select(Match))).scalars().all()
        assert len(matches) == 1
        # Adapter must be closed
        assert fake_adapter.closed is True

    async def test_swallows_per_sport_ingestion_exception(
        self, patch_async_session, db_session, monkeypatch, caplog
    ):
        """Una falla en ingestion de un sport NO debe matar el job ni los demás sports.

        Antes el outer try/except lo atrapaba todo y el job entero quedaba
        marcado como 'Fetch odds job failed'. Ahora cada sport falla por
        separado y los siguientes siguen ejecutándose; se loguea con stack
        ('Sport X fetch failed') y el adapter se cierra correctamente.
        """
        import logging
        from app.config import settings
        monkeypatch.setattr(settings, "ODDS_API_KEY", "fake-key")
        await seed_database(db_session)

        adapter = FakeAdapter()
        monkeypatch.setattr(jobs_module, "OddsAPIAdapter", lambda *a, **kw: adapter)

        class BoomIngestion:
            def __init__(self, *a, **kw): ...
            async def ingest_odds(self, *a, **kw):
                raise RuntimeError("ingestion down")

        monkeypatch.setattr(jobs_module, "OddsIngestionService", BoomIngestion)

        with caplog.at_level(logging.ERROR, logger="app.workers.jobs"):
            await jobs_module.fetch_odds_job()  # must not raise
        # Ahora el log es por-sport, no a nivel job
        assert any("fetch failed" in rec.message.lower() for rec in caplog.records)
        assert adapter.closed is True


class TestDetectValueJob:
    async def test_finds_opportunities_and_notifies(
        self, patch_async_session, db_session, monkeypatch
    ):
        await seed_database(db_session)

        commence = datetime.now(timezone.utc) + timedelta(days=1)
        # Outlier at WH creates a value bet
        data = [
            _raw("V1", "V2", "bet365",
                 [("V1", 2.10), ("Draw", 3.30), ("V2", 3.60)], commence),
            _raw("V1", "V2", "pinnacle",
                 [("V1", 2.12), ("Draw", 3.25), ("V2", 3.55)], commence),
            _raw("V1", "V2", "betfair_ex_eu",
                 [("V1", 2.08), ("Draw", 3.35), ("V2", 3.65)], commence),
            _raw("V1", "V2", "williamhill",
                 [("V1", 2.60), ("Draw", 2.90), ("V2", 2.80)], commence),
        ]
        await OddsIngestionService(FakeAdapter(data)).ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_spain_la_liga"]
        )
        await _make_user_with_alert(db_session, dest="chat-val")

        # Stub the NotificationService that the job imports
        notify_mock = AsyncMock(return_value={"sent": 1, "failed": 0})
        with patch(
            "app.notifications.service.NotificationService.notify_new_opportunities",
            notify_mock,
        ):
            await jobs_module.detect_value_job()

        opps = (
            await db_session.execute(
                select(Opportunity).where(Opportunity.status == "active")
            )
        ).scalars().all()
        assert len(opps) >= 1
        notify_mock.assert_awaited()

    async def test_no_notification_when_nothing_found(
        self, patch_async_session, db_session
    ):
        await seed_database(db_session)

        with patch(
            "app.notifications.service.NotificationService.notify_new_opportunities",
            new=AsyncMock(return_value={"sent": 0, "failed": 0}),
        ) as notify_mock:
            await jobs_module.detect_value_job()

        # No opps → still ok, notifier may or may not be called with []
        # (the job only calls when new_opportunities is truthy)
        assert notify_mock.await_count == 0

    async def test_swallows_exception(
        self, patch_async_session, monkeypatch, caplog
    ):
        import logging

        class BoomService:
            def __init__(self, *a, **kw): ...
            async def detect_all(self, db):
                raise RuntimeError("db on fire")

        monkeypatch.setattr(
            jobs_module, "OpportunityDetectionService", BoomService
        )
        with caplog.at_level(logging.ERROR, logger="app.workers.jobs"):
            await jobs_module.detect_value_job()
        assert any("Detect value job failed" in r.message for r in caplog.records)


class TestDetectArbitrageJob:
    async def test_finds_arb_and_dispatches_telegram(
        self, patch_async_session, db_session, monkeypatch
    ):
        await seed_database(db_session)

        commence = datetime.now(timezone.utc) + timedelta(days=1)
        data = [
            _raw("AH", "AA", "bet365",
                 [("AH", 2.60), ("Draw", 3.10), ("AA", 3.20)], commence),
            _raw("AH", "AA", "pinnacle",
                 [("AH", 2.00), ("Draw", 3.80), ("AA", 3.20)], commence),
            _raw("AH", "AA", "betfair_ex_eu",
                 [("AH", 2.00), ("Draw", 3.10), ("AA", 4.20)], commence),
            _raw("AH", "AA", "williamhill",
                 [("AH", 2.30), ("Draw", 3.40), ("AA", 3.60)], commence),
            _raw("AH", "AA", "unibet_eu",
                 [("AH", 2.10), ("Draw", 3.50), ("AA", 3.50)], commence),
        ]
        await OddsIngestionService(FakeAdapter(data)).ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_spain_la_liga"]
        )
        await _make_user_with_alert(db_session, dest="chat-arb")

        # Fake TelegramNotifier: record sends + close
        calls: list[tuple[str, object]] = []

        class FakeTelegram:
            async def send(self, dest, payload, currency=""):
                calls.append((dest, payload))
                return True

            async def close(self):
                pass

        # The job imports TelegramNotifier inside the function, so patch the source module
        import app.notifications.telegram_notifier as tg_mod
        monkeypatch.setattr(tg_mod, "TelegramNotifier", FakeTelegram)

        await jobs_module.detect_arbitrage_job()

        arbs = (
            await db_session.execute(select(ArbitrageOpportunity))
        ).scalars().all()
        assert len(arbs) >= 1
        assert len(calls) >= 1
        dest, payload = calls[0]
        assert dest == "chat-arb"
        # Arbitrage payload has these fields
        assert payload.profit_pct > 0

    async def test_no_op_when_no_arb_found(
        self, patch_async_session, db_session, monkeypatch
    ):
        await seed_database(db_session)
        # No matches ingested → detect_all finds nothing
        calls = []

        class FakeTelegram:
            async def send(self, dest, payload, currency=""):
                calls.append((dest, payload))
                return True
            async def close(self):
                pass

        import app.notifications.telegram_notifier as tg_mod
        monkeypatch.setattr(tg_mod, "TelegramNotifier", FakeTelegram)

        await jobs_module.detect_arbitrage_job()
        assert calls == []

    async def test_swallows_exception(
        self, patch_async_session, monkeypatch, caplog
    ):
        import logging

        class BoomService:
            def __init__(self, *a, **kw): ...
            async def detect_all(self, db):
                raise RuntimeError("explode")

        # Patch where the job imports it from
        import app.services.arbitrage_service as arb_mod
        monkeypatch.setattr(arb_mod, "ArbitrageDetectionService", BoomService)

        with caplog.at_level(logging.ERROR, logger="app.workers.jobs"):
            await jobs_module.detect_arbitrage_job()
        assert any("Detect arbitrage job failed" in r.message for r in caplog.records)


class TestCaptureClosingLinesJob:
    async def test_captures_when_match_is_imminent(
        self, patch_async_session, db_session
    ):
        await seed_database(db_session)

        # Match kicking off in 2 minutes → inside 5-min window
        commence = datetime.now(timezone.utc) + timedelta(minutes=2)
        data = [
            _raw("CH", "CA", "bet365",
                 [("CH", 2.10), ("Draw", 3.30), ("CA", 3.60)], commence),
            _raw("CH", "CA", "pinnacle",
                 [("CH", 2.12), ("Draw", 3.25), ("CA", 3.55)], commence),
        ]
        await OddsIngestionService(FakeAdapter(data)).ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_spain_la_liga"]
        )

        await jobs_module.capture_closing_lines_job()

        lines = (await db_session.execute(select(ClosingLine))).scalars().all()
        # 3 outcomes × 2 bookmakers = 6 closing lines
        assert len(lines) == 6

    async def test_skips_matches_outside_window(
        self, patch_async_session, db_session
    ):
        await seed_database(db_session)

        # Match in 2 hours → well outside the 5-min window
        commence = datetime.now(timezone.utc) + timedelta(hours=2)
        data = [
            _raw("FH", "FA", "bet365",
                 [("FH", 2.10), ("Draw", 3.30), ("FA", 3.60)], commence),
        ]
        await OddsIngestionService(FakeAdapter(data)).ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_spain_la_liga"]
        )

        await jobs_module.capture_closing_lines_job()

        lines = (await db_session.execute(select(ClosingLine))).scalars().all()
        assert lines == []

    async def test_idempotent_on_reruns(
        self, patch_async_session, db_session
    ):
        """On conflict do nothing: running twice must not duplicate rows."""
        await seed_database(db_session)
        commence = datetime.now(timezone.utc) + timedelta(minutes=2)
        data = [
            _raw("IH", "IA", "bet365",
                 [("IH", 2.10), ("Draw", 3.30), ("IA", 3.60)], commence),
        ]
        await OddsIngestionService(FakeAdapter(data)).ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_spain_la_liga"]
        )

        await jobs_module.capture_closing_lines_job()
        count1 = len((await db_session.execute(select(ClosingLine))).scalars().all())

        await jobs_module.capture_closing_lines_job()
        count2 = len((await db_session.execute(select(ClosingLine))).scalars().all())

        assert count1 == count2 == 3

    async def test_backfills_closing_odds_on_paper_bets(
        self, patch_async_session, db_session
    ):
        """El job debe rellenar PaperBet.closing_odds para el (outcome, bookmaker) apostado."""
        await seed_database(db_session)
        commence = datetime.now(timezone.utc) + timedelta(minutes=2)
        data = [
            _raw("BH", "BA", "bet365",
                 [("BH", 2.10), ("Draw", 3.30), ("BA", 3.60)], commence),
            _raw("BH", "BA", "pinnacle",
                 [("BH", 2.05), ("Draw", 3.40), ("BA", 3.70)], commence),
        ]
        await OddsIngestionService(FakeAdapter(data)).ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_spain_la_liga"]
        )

        match = (await db_session.execute(select(Match))).scalar_one()
        # Apuesta sobre el outcome BH en bet365
        bh_outcome = (
            await db_session.execute(
                select(Outcome).where(Outcome.key == "home")
            )
        ).scalar_one()
        bet365 = (
            await db_session.execute(
                select(Bookmaker).where(Bookmaker.key == "bet365")
            )
        ).scalar_one()
        paper = PaperBet(
            source_type="value",
            match_id=match.id,
            outcome_id=bh_outcome.id,
            bookmaker_id=bet365.id,
            odds_taken=Decimal("2.20"),  # tomamos cuota mejor que la final
            stake_units=Decimal("0.005"),
            ev_at_placement=Decimal("0.04"),
        )
        db_session.add(paper)
        await db_session.commit()

        await jobs_module.capture_closing_lines_job()

        await db_session.refresh(paper)
        # closing line de bet365 para BH = 2.10
        assert paper.closing_odds == Decimal("2.1000")

    async def test_backfill_does_not_overwrite_existing(
        self, patch_async_session, db_session
    ):
        """Un closing_odds ya rellenado no debe ser pisado por reruns posteriores."""
        await seed_database(db_session)
        commence = datetime.now(timezone.utc) + timedelta(minutes=2)
        data = [
            _raw("OH", "OA", "bet365",
                 [("OH", 2.50), ("Draw", 3.10), ("OA", 2.80)], commence),
        ]
        await OddsIngestionService(FakeAdapter(data)).ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_spain_la_liga"]
        )

        match = (await db_session.execute(select(Match))).scalar_one()
        oh_outcome = (
            await db_session.execute(
                select(Outcome).where(Outcome.key == "home")
            )
        ).scalar_one()
        bet365 = (
            await db_session.execute(
                select(Bookmaker).where(Bookmaker.key == "bet365")
            )
        ).scalar_one()
        # Pre-existing closing capturado en una corrida anterior con cuota distinta
        paper = PaperBet(
            source_type="value",
            match_id=match.id,
            outcome_id=oh_outcome.id,
            bookmaker_id=bet365.id,
            odds_taken=Decimal("2.60"),
            stake_units=Decimal("0.003"),
            closing_odds=Decimal("2.4000"),
        )
        db_session.add(paper)
        await db_session.commit()

        await jobs_module.capture_closing_lines_job()

        await db_session.refresh(paper)
        assert paper.closing_odds == Decimal("2.4000")


class TestCleanupJob:
    async def test_marks_past_matches_completed(
        self, patch_async_session, db_session
    ):
        await seed_database(db_session)
        commence_past = datetime.now(timezone.utc) - timedelta(hours=2)
        data = [
            _raw("PH", "PA", "bet365",
                 [("PH", 2.10), ("Draw", 3.30), ("PA", 3.60)], commence_past),
        ]
        await OddsIngestionService(FakeAdapter(data)).ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_spain_la_liga"]
        )

        # Ensure status=scheduled pre-cleanup
        match = (await db_session.execute(select(Match))).scalar_one()
        match.status = "scheduled"
        await db_session.commit()

        await jobs_module.cleanup_job()

        await db_session.refresh(match)
        assert match.status == "completed"

    async def test_leaves_future_matches_alone(
        self, patch_async_session, db_session
    ):
        await seed_database(db_session)
        commence_future = datetime.now(timezone.utc) + timedelta(hours=2)
        data = [
            _raw("FH2", "FA2", "bet365",
                 [("FH2", 2.10), ("Draw", 3.30), ("FA2", 3.60)], commence_future),
        ]
        await OddsIngestionService(FakeAdapter(data)).ingest_odds(
            db_session, sport_key="football", league_keys=["soccer_spain_la_liga"]
        )

        await jobs_module.cleanup_job()

        match = (await db_session.execute(select(Match))).scalar_one()
        assert match.status == "scheduled"

    async def test_swallows_exception(
        self, patch_async_session, monkeypatch, caplog
    ):
        import logging

        # Force async_session to fail
        class BoomSession:
            def __call__(self):
                raise RuntimeError("session factory down")

        monkeypatch.setattr(jobs_module, "async_session", BoomSession())
        with caplog.at_level(logging.ERROR, logger="app.workers.jobs"):
            await jobs_module.cleanup_job()
        assert any("Cleanup job failed" in r.message for r in caplog.records)
