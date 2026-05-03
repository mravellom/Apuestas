"""Tests integración de steam detection."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import RawOddsData, RawOutcome
from app.core.steam import detect_steam_signal
from app.models.bookmaker import Bookmaker
from app.models.market import Odds, Outcome
from app.models.match import Match
from app.services.odds_service import OddsIngestionService
from app.services.seed_service import seed_database


class _FakeAdapter:
    def __init__(self, data):
        self.odds_data = data

    async def fetch_odds(self, sport, regions=None, markets=None):
        return self.odds_data

    async def fetch_events(self, sport):
        return []

    async def close(self):
        pass


def _raw(home, away, bk, outcomes, commence):
    return RawOddsData(
        source="test",
        sport_key="soccer_spain_la_liga",
        league_key="soccer_spain_la_liga",
        home_team=home,
        away_team=away,
        commence_time=commence,
        bookmaker=bk,
        market_type="h2h",
        outcomes=[RawOutcome(name=n, price=p) for n, p in outcomes],
        external_id=f"steam_test_{home}_{away}_{bk}",
    )


async def _seed_match(db: AsyncSession):
    await seed_database(db)
    commence = datetime.now(timezone.utc) + timedelta(hours=2)
    data = [
        _raw("SH", "SA", "pinnacle", [("SH", 2.10), ("Draw", 3.30), ("SA", 3.60)], commence),
        _raw("SH", "SA", "bet365", [("SH", 2.10), ("Draw", 3.30), ("SA", 3.60)], commence),
    ]
    await OddsIngestionService(_FakeAdapter(data)).ingest_odds(
        db, sport_key="football", league_keys=["soccer_spain_la_liga"]
    )
    outcome = (await db.execute(select(Outcome).where(Outcome.key == "sh"))).scalar_one()
    return outcome


async def _add_old_odds(db, outcome_id, bookmaker_key, price, minutes_ago):
    bm = (
        await db.execute(select(Bookmaker).where(Bookmaker.key == bookmaker_key))
    ).scalar_one()
    captured = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes_ago)
    db.add(
        Odds(
            outcome_id=outcome_id,
            bookmaker_id=bm.id,
            price=Decimal(str(price)),
            captured_at=captured,
            source="test",
        )
    )
    await db.flush()


class TestSteamDetection:
    async def test_no_steam_when_sharps_stable(self, db_session: AsyncSession):
        outcome = await _seed_match(db_session)
        # Solo hay 1 muestra reciente por book → no hay velocidad medible
        signal = await detect_steam_signal(db_session, outcome.id)
        assert signal.is_steam is False

    async def test_steam_when_sharp_moves_above_threshold(
        self, db_session: AsyncSession
    ):
        outcome = await _seed_match(db_session)
        # Pinnacle hace 3 minutos estaba a 2.50 (impl 0.40), ahora a 2.10 (impl 0.476).
        # Δ = +0.076, supera el threshold default de 0.02.
        await _add_old_odds(db_session, outcome.id, "pinnacle", 2.50, minutes_ago=3)
        signal = await detect_steam_signal(db_session, outcome.id)
        assert signal.is_steam is True
        assert "pinnacle" in signal.moved_books
        assert signal.direction == "shortening"

    async def test_no_steam_when_move_below_threshold(self, db_session: AsyncSession):
        outcome = await _seed_match(db_session)
        # Movimiento mínimo: 2.12 → 2.10 (Δ implícita ≈ 0.0045)
        await _add_old_odds(db_session, outcome.id, "pinnacle", 2.12, minutes_ago=3)
        signal = await detect_steam_signal(db_session, outcome.id)
        assert signal.is_steam is False

    async def test_only_considers_sharp_books(self, db_session: AsyncSession):
        outcome = await _seed_match(db_session)
        # Bet365 (no sharp) se mueve fuerte: NO debe contar como steam.
        await _add_old_odds(db_session, outcome.id, "bet365", 2.50, minutes_ago=3)
        signal = await detect_steam_signal(db_session, outcome.id)
        assert signal.is_steam is False

    async def test_window_excludes_old_samples(self, db_session: AsyncSession):
        outcome = await _seed_match(db_session)
        # Movimiento fuerte fuera del window de 5min default → no cuenta
        await _add_old_odds(db_session, outcome.id, "pinnacle", 2.50, minutes_ago=20)
        signal = await detect_steam_signal(db_session, outcome.id)
        assert signal.is_steam is False
