"""Tests unitarios del paper trading service."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.value_detector import ValueBet
from app.services.paper_trading_service import DEFAULT_STAKE_UNITS, PaperTradingService


@pytest.mark.asyncio
async def test_record_value_bet_uses_kelly_when_positive():
    svc = PaperTradingService()
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    vb = ValueBet(
        outcome_index=0,
        outcome_key="burnley",
        bookmaker_key="coolbet",
        bookmaker_odds=7.7,
        consensus_prob=0.1316,
        implied_prob=0.1299,
        value_pct=0.0134,
        kelly_full=0.002,
        edge_confidence="reference",
    )
    opp = MagicMock(id=42, outcome_id=1, bookmaker_id=2)

    paper = await svc.record_value_bet(db, opp, vb, match_id=10)
    assert paper.source_type == "value"
    assert paper.opportunity_id == 42
    assert paper.match_id == 10
    assert paper.odds_taken == Decimal("7.7")
    assert paper.stake_units == Decimal("0.002")
    assert paper.ev_at_placement == Decimal("0.0134")


@pytest.mark.asyncio
async def test_record_value_bet_falls_back_to_default_stake_when_kelly_zero():
    svc = PaperTradingService()
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    vb = ValueBet(
        outcome_index=0, outcome_key="x", bookmaker_key="x",
        bookmaker_odds=2.0, consensus_prob=0.5, implied_prob=0.5,
        value_pct=0.01, kelly_full=0.0, edge_confidence="reference",
    )
    opp = MagicMock(id=1, outcome_id=1, bookmaker_id=1)
    paper = await svc.record_value_bet(db, opp, vb, match_id=1)
    assert paper.stake_units == DEFAULT_STAKE_UNITS


@pytest.mark.asyncio
async def test_settle_match_missing_scores_returns_zero():
    svc = PaperTradingService()
    db = MagicMock()
    match = MagicMock(home_score=None, away_score=None, id=1)
    result = await svc.settle_match(db, match)
    assert result == {"settled": 0, "skipped": 0}


class TestSettlement:
    """Tests de cálculo de profit con DB mock controlado."""

    def _make_paper(self, outcome_key: str, odds: str, stake: str):
        paper = MagicMock()
        paper.result = "pending"
        paper.odds_taken = Decimal(odds)
        paper.stake_units = Decimal(stake)
        paper.profit_units = None
        paper.resolved_at = None
        outcome = MagicMock()
        outcome.key = outcome_key
        return paper, outcome

    @pytest.mark.asyncio
    async def test_home_win_settles_home_bet_as_won(self):
        svc = PaperTradingService()
        paper_home, out_home = self._make_paper("burnley", "7.7", "0.002")
        paper_away, out_away = self._make_paper("nottingham_forest", "1.49", "0.002")

        db = MagicMock()
        db.execute = AsyncMock()
        home_team = MagicMock(canonical_name="Burnley")
        away_team = MagicMock(canonical_name="Nottingham Forest")

        # Two selects: home team, away team, then pending paper bets
        team_result1, team_result2, pending_result = MagicMock(), MagicMock(), MagicMock()
        team_result1.scalar_one.return_value = home_team
        team_result2.scalar_one.return_value = away_team
        pending_result.all.return_value = [(paper_home, out_home), (paper_away, out_away)]
        db.execute.side_effect = [team_result1, team_result2, pending_result]

        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=2, away_score=1)
        r = await svc.settle_match(db, match)

        assert r["settled"] == 2
        assert paper_home.result == "won"
        assert paper_home.profit_units == Decimal("0.002") * (Decimal("7.7") - Decimal("1"))
        assert paper_away.result == "lost"
        assert paper_away.profit_units == -Decimal("0.002")

    @pytest.mark.asyncio
    async def test_draw_settles_draw_as_won(self):
        svc = PaperTradingService()
        paper_draw, out_draw = self._make_paper("draw", "3.5", "0.01")
        paper_home, out_home = self._make_paper("burnley", "7.7", "0.01")

        db = MagicMock()
        db.execute = AsyncMock()
        home_team = MagicMock(canonical_name="Burnley")
        away_team = MagicMock(canonical_name="Nottingham Forest")
        team_result1, team_result2, pending_result = MagicMock(), MagicMock(), MagicMock()
        team_result1.scalar_one.return_value = home_team
        team_result2.scalar_one.return_value = away_team
        pending_result.all.return_value = [(paper_draw, out_draw), (paper_home, out_home)]
        db.execute.side_effect = [team_result1, team_result2, pending_result]

        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=1, away_score=1)
        await svc.settle_match(db, match)

        assert paper_draw.result == "won"
        assert paper_home.result == "lost"
