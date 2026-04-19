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
from app.models.market import ClosingLine, Odds, Outcome
from app.models.match import Match
from app.models.opportunity import Opportunity
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

    async def test_swallows_adapter_exception(
        self, patch_async_session, monkeypatch, caplog
    ):
        """Even if ingestion blows up, the job must close the adapter and log."""
        import logging
        from app.config import settings
        monkeypatch.setattr(settings, "ODDS_API_KEY", "fake-key")

        adapter = FakeAdapter()
        monkeypatch.setattr(jobs_module, "OddsAPIAdapter", lambda *a, **kw: adapter)

        class BoomIngestion:
            def __init__(self, *a, **kw): ...
            async def ingest_odds(self, *a, **kw):
                raise RuntimeError("ingestion down")

        monkeypatch.setattr(jobs_module, "OddsIngestionService", BoomIngestion)

        with caplog.at_level(logging.ERROR, logger="app.workers.jobs"):
            await jobs_module.fetch_odds_job()  # must not raise
        assert any("Fetch odds job failed" in rec.message for rec in caplog.records)
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
