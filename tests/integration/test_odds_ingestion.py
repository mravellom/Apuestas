"""Regression tests para la capa de ingesta de cuotas — foco en bug #4."""

from datetime import datetime, timedelta, timezone

import pytest

from app.adapters.base import DataSourceAdapter, RawOddsData, RawOutcome
from app.adapters.normalizer import TeamNormalizer
from app.models.bookmaker import Bookmaker
from app.models.market import MarketType, Odds, Outcome
from app.models.sport import League, Season, Sport
from app.services.odds_service import OddsIngestionService
from sqlalchemy import select


class _StubAdapter(DataSourceAdapter):
    def __init__(self, data):
        self._data = data

    async def fetch_odds(self, sport, regions=None, markets=None):
        return self._data

    async def fetch_events(self, sport):
        return []


async def _min_setup(db, league_key="soccer_epl"):
    sport = Sport(key="football", name="Football")
    db.add(sport)
    await db.flush()
    league = League(sport_id=sport.id, key=league_key, name="EPL", active=True)
    db.add(league)
    await db.flush()
    season = Season(league_id=league.id, name="2025-2026", active=True)
    db.add(season)

    mt = MarketType(key="h2h", name="Match Result")
    db.add(mt)

    # Seed solo PINNACLE; el feed también trae "unknownbook" que NO debe ser creado.
    db.add(Bookmaker(key="pinnacle", name="Pinnacle", is_sharp=True, active=True))
    await db.commit()


@pytest.mark.asyncio
async def test_unknown_bookmaker_skipped_not_autocreated(db_session, caplog):
    """Bug #4: bookmaker desconocido no debe autocrearse con commission=0."""
    import logging

    await _min_setup(db_session)

    commence = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5)
    raw = [
        RawOddsData(
            source="test",
            sport_key="football",
            league_key="soccer_epl",
            home_team="Arsenal",
            away_team="Chelsea",
            commence_time=commence,
            bookmaker="pinnacle",
            market_type="h2h",
            outcomes=[RawOutcome(name="Arsenal", price=2.1), RawOutcome(name="Chelsea", price=3.3), RawOutcome(name="Draw", price=3.4)],
            parameter=None,
            external_id="evt-1",
        ),
        RawOddsData(
            source="test",
            sport_key="football",
            league_key="soccer_epl",
            home_team="Arsenal",
            away_team="Chelsea",
            commence_time=commence,
            bookmaker="unknownbook",
            market_type="h2h",
            outcomes=[RawOutcome(name="Arsenal", price=2.2), RawOutcome(name="Chelsea", price=3.5), RawOutcome(name="Draw", price=3.3)],
            parameter=None,
            external_id="evt-1",
        ),
    ]

    service = OddsIngestionService(_StubAdapter(raw), TeamNormalizer())

    with caplog.at_level(logging.WARNING, logger="app.services.odds_service"):
        await service.ingest_odds(db_session, sport_key="football", league_keys=["soccer_epl"])

    # Pinnacle sí ingesta, unknownbook no.
    bookmakers = (
        await db_session.execute(select(Bookmaker).order_by(Bookmaker.key))
    ).scalars().all()
    keys = [b.key for b in bookmakers]
    assert "pinnacle" in keys
    assert "unknownbook" not in keys

    # Odds de pinnacle sí, de unknownbook no.
    odds = (await db_session.execute(select(Odds))).scalars().all()
    assert len(odds) == 3  # 3 outcomes × 1 book
    assert all(o.bookmaker_id == bookmakers[keys.index("pinnacle")].id for o in odds)

    # Warning loggeado exactamente una vez.
    warnings = [r for r in caplog.records if "Unknown bookmaker 'unknownbook'" in r.message]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_inactive_bookmaker_not_used_in_ingestion(db_session):
    """Un bookmaker con active=False (ej. fantasma deshabilitado) no debe recibir odds nuevos."""
    await _min_setup(db_session)
    # Agregar bookmaker inactivo
    db_session.add(Bookmaker(key="ghostbook", name="Ghost", is_sharp=False, active=False))
    await db_session.commit()

    commence = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5)
    raw = [
        RawOddsData(
            source="test", sport_key="football", league_key="soccer_epl",
            home_team="A", away_team="B", commence_time=commence,
            bookmaker="ghostbook", market_type="h2h",
            outcomes=[RawOutcome(name="A", price=2.0), RawOutcome(name="B", price=2.0), RawOutcome(name="Draw", price=3.0)],
            parameter=None, external_id="e1",
        ),
    ]

    service = OddsIngestionService(_StubAdapter(raw), TeamNormalizer())
    await service.ingest_odds(db_session, sport_key="football", league_keys=["soccer_epl"])

    # Ningún odd nuevo — el bookmaker inactivo es tratado como desconocido.
    odds = (await db_session.execute(select(Odds))).scalars().all()
    assert odds == []
