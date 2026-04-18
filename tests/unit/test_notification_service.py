"""Tests para NotificationService: filtros, canales y manejo de errores."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.models.alert import AlertConfig
from app.models.opportunity import Opportunity
from app.models.user import User, UserConfig
from app.notifications import service as notif_service_module
from app.notifications.base import NotificationPayload, Notifier
from app.notifications.service import NotificationService
from app.services.auth_service import hash_password
from app.services.odds_service import OddsIngestionService
from app.services.opportunity_service import OpportunityDetectionService
from app.services.seed_service import seed_database


class FakeAdapter(DataSourceAdapter):
    def __init__(self, odds_data: list[RawOddsData]):
        self.odds_data = odds_data

    async def fetch_odds(self, sport, regions=None, markets=None):
        return self.odds_data

    async def fetch_events(self, sport):
        return []


class RecordingNotifier(Notifier):
    """Notifier en memoria que graba llamadas para inspección."""

    def __init__(self, *, return_value: bool = True, raise_exc: bool = False):
        self.calls: list[tuple[str, NotificationPayload]] = []
        self.return_value = return_value
        self.raise_exc = raise_exc

    async def send(self, destination: str, payload: NotificationPayload) -> bool:
        self.calls.append((destination, payload))
        if self.raise_exc:
            raise RuntimeError("boom")
        return self.return_value


@pytest.fixture(autouse=True)
def _clear_notifier_cache():
    """Evita que el singleton por canal contamine tests entre sí."""
    notif_service_module._NOTIFIERS.clear()
    yield
    notif_service_module._NOTIFIERS.clear()


@pytest.fixture
def patch_notifier(monkeypatch):
    """Inyecta un notifier fake en el factory de NotificationService."""

    def _apply(notifier: Notifier):
        def fake_get(channel: str):
            return notifier

        monkeypatch.setattr(notif_service_module, "_get_notifier", fake_get)
        return notifier

    return _apply


async def _seed_user(db: AsyncSession, email: str = "alerts@test.com") -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        username=email.split("@")[0],
        hashed_password=hash_password("x" * 10),
        role="premium",
    )
    db.add(user)
    db.add(UserConfig(user_id=user.id))
    await db.flush()
    return user


async def _setup_opportunities(db: AsyncSession) -> list[Opportunity]:
    """Crea un match con odds outlier y detecta value bets reales."""
    await seed_database(db)

    commence = datetime.now(timezone.utc) + timedelta(days=1)
    fake_data = [
        RawOddsData(
            source="test",
            sport_key="soccer_spain_la_liga",
            league_key="soccer_spain_la_liga",
            home_team="Home",
            away_team="Away",
            commence_time=commence,
            bookmaker=bk,
            market_type="h2h",
            outcomes=[
                RawOutcome(name="Home", price=odds[0]),
                RawOutcome(name="Draw", price=odds[1]),
                RawOutcome(name="Away", price=odds[2]),
            ],
            external_id=f"notif_test_{bk}",
        )
        for bk, odds in [
            ("bet365", (2.10, 3.30, 3.60)),
            ("pinnacle", (2.12, 3.25, 3.55)),
            ("betfair_ex_eu", (2.08, 3.35, 3.65)),
            # WH outlier → creates value bet on Home
            ("williamhill", (2.60, 2.90, 2.80)),
        ]
    ]

    await OddsIngestionService(FakeAdapter(fake_data)).ingest_odds(
        db, sport_key="football", league_keys=["soccer_spain_la_liga"]
    )

    detector = OpportunityDetectionService(min_value=0.01, min_bookmakers=3)
    _, new_opps = await detector.detect_all(db)
    assert new_opps, "precondition: detector must find at least one opportunity"
    return new_opps


class TestEmptyCases:
    async def test_no_opportunities_returns_zero_counts(
        self, db_session: AsyncSession
    ):
        svc = NotificationService()
        counts = await svc.notify_new_opportunities(db_session, [])
        assert counts == {"sent": 0, "failed": 0}

    async def test_no_active_alerts_returns_zero(
        self, db_session: AsyncSession, patch_notifier
    ):
        opps = await _setup_opportunities(db_session)
        notifier = patch_notifier(RecordingNotifier())

        svc = NotificationService()
        counts = await svc.notify_new_opportunities(db_session, opps)

        assert counts == {"sent": 0, "failed": 0}
        assert notifier.calls == []


class TestFiltering:
    async def test_respects_min_value_filter(
        self, db_session: AsyncSession, patch_notifier
    ):
        opps = await _setup_opportunities(db_session)
        user = await _seed_user(db_session)

        # Alert threshold HIGHER than any opportunity's value — nothing should fire
        max_value = max(float(o.value_pct) for o in opps)
        db_session.add(
            AlertConfig(
                user_id=user.id,
                channel="telegram",
                destination="123",
                min_value_pct=Decimal(str(max_value + 0.5)),
                active=True,
            )
        )
        await db_session.flush()

        notifier = patch_notifier(RecordingNotifier())
        svc = NotificationService()
        counts = await svc.notify_new_opportunities(db_session, opps)

        assert counts["sent"] == 0
        assert counts["failed"] == 0
        assert notifier.calls == []

    async def test_sports_filter_excludes_other_sports(
        self, db_session: AsyncSession, patch_notifier
    ):
        opps = await _setup_opportunities(db_session)
        user = await _seed_user(db_session)

        db_session.add(
            AlertConfig(
                user_id=user.id,
                channel="telegram",
                destination="123",
                min_value_pct=Decimal("0.0"),
                sports_filter=["basketball"],  # opps are football → excluded
                active=True,
            )
        )
        await db_session.flush()

        notifier = patch_notifier(RecordingNotifier())
        counts = await NotificationService().notify_new_opportunities(db_session, opps)

        assert notifier.calls == []
        assert counts["sent"] == 0

    async def test_sports_filter_includes_matching_sport(
        self, db_session: AsyncSession, patch_notifier
    ):
        opps = await _setup_opportunities(db_session)
        user = await _seed_user(db_session)

        db_session.add(
            AlertConfig(
                user_id=user.id,
                channel="telegram",
                destination="123",
                min_value_pct=Decimal("0.0"),
                sports_filter=["football"],
                active=True,
            )
        )
        await db_session.flush()

        notifier = patch_notifier(RecordingNotifier())
        counts = await NotificationService().notify_new_opportunities(db_session, opps)

        assert counts["sent"] >= 1
        assert notifier.calls

    async def test_inactive_alerts_are_skipped(
        self, db_session: AsyncSession, patch_notifier
    ):
        opps = await _setup_opportunities(db_session)
        user = await _seed_user(db_session)

        db_session.add(
            AlertConfig(
                user_id=user.id,
                channel="telegram",
                destination="inactive",
                min_value_pct=Decimal("0.0"),
                active=False,
            )
        )
        await db_session.flush()

        notifier = patch_notifier(RecordingNotifier())
        counts = await NotificationService().notify_new_opportunities(db_session, opps)

        assert counts == {"sent": 0, "failed": 0}
        assert notifier.calls == []


class TestDelivery:
    async def test_successful_send_counts_as_sent(
        self, db_session: AsyncSession, patch_notifier
    ):
        opps = await _setup_opportunities(db_session)
        user = await _seed_user(db_session)
        db_session.add(
            AlertConfig(
                user_id=user.id,
                channel="telegram",
                destination="chat-1",
                min_value_pct=Decimal("0.0"),
                active=True,
            )
        )
        await db_session.flush()

        notifier = patch_notifier(RecordingNotifier(return_value=True))
        counts = await NotificationService().notify_new_opportunities(db_session, opps)

        assert counts["sent"] == len(opps)
        assert counts["failed"] == 0
        assert len(notifier.calls) == len(opps)
        dest, payload = notifier.calls[0]
        assert dest == "chat-1"
        assert isinstance(payload, NotificationPayload)
        assert payload.match_home and payload.match_away
        assert payload.odds_price > 1.0

    async def test_failed_send_counts_as_failed(
        self, db_session: AsyncSession, patch_notifier
    ):
        opps = await _setup_opportunities(db_session)
        user = await _seed_user(db_session)
        db_session.add(
            AlertConfig(
                user_id=user.id,
                channel="telegram",
                destination="chat-2",
                min_value_pct=Decimal("0.0"),
                active=True,
            )
        )
        await db_session.flush()

        patch_notifier(RecordingNotifier(return_value=False))
        counts = await NotificationService().notify_new_opportunities(db_session, opps)

        assert counts["failed"] == len(opps)
        assert counts["sent"] == 0

    async def test_exception_is_swallowed_and_counted_as_failed(
        self, db_session: AsyncSession, patch_notifier
    ):
        opps = await _setup_opportunities(db_session)
        user = await _seed_user(db_session)
        db_session.add(
            AlertConfig(
                user_id=user.id,
                channel="telegram",
                destination="chat-3",
                min_value_pct=Decimal("0.0"),
                active=True,
            )
        )
        await db_session.flush()

        patch_notifier(RecordingNotifier(raise_exc=True))
        # Must not propagate — the service is designed to be resilient
        counts = await NotificationService().notify_new_opportunities(db_session, opps)

        assert counts["failed"] == len(opps)
        assert counts["sent"] == 0

    async def test_fans_out_to_multiple_alerts(
        self, db_session: AsyncSession, patch_notifier
    ):
        opps = await _setup_opportunities(db_session)
        user_a = await _seed_user(db_session, "a@test.com")
        user_b = await _seed_user(db_session, "b@test.com")

        for user, dest in [(user_a, "chat-a"), (user_b, "chat-b")]:
            db_session.add(
                AlertConfig(
                    user_id=user.id,
                    channel="telegram",
                    destination=dest,
                    min_value_pct=Decimal("0.0"),
                    active=True,
                )
            )
        await db_session.flush()

        notifier = patch_notifier(RecordingNotifier())
        counts = await NotificationService().notify_new_opportunities(db_session, opps)

        assert counts["sent"] == len(opps) * 2
        destinations = {d for d, _ in notifier.calls}
        assert destinations == {"chat-a", "chat-b"}


class TestPayloadConstruction:
    async def test_payload_fields_match_opportunity(
        self, db_session: AsyncSession, patch_notifier
    ):
        opps = await _setup_opportunities(db_session)
        user = await _seed_user(db_session)
        db_session.add(
            AlertConfig(
                user_id=user.id,
                channel="telegram",
                destination="inspect",
                min_value_pct=Decimal("0.0"),
                active=True,
            )
        )
        await db_session.flush()

        notifier = patch_notifier(RecordingNotifier())
        await NotificationService().notify_new_opportunities(db_session, opps[:1])

        assert len(notifier.calls) == 1
        _, payload = notifier.calls[0]
        opp = opps[0]
        assert payload.odds_price == float(opp.odds_price)
        assert payload.value_pct == float(opp.value_pct)
        assert payload.consensus_prob == float(opp.consensus_prob)
        # Full message should be formattable
        msg = payload.format_message()
        assert "VALUE BET" in msg
