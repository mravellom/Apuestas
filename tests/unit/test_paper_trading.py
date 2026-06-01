"""Tests unitarios del paper trading service."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.value_detector import ValueBet
from app.services.paper_trading_service import (
    DEFAULT_STAKE_UNITS,
    PAPER_KELLY_FRACTION,
    PAPER_MAX_STAKE_UNITS,
    PAPER_MAX_TOTAL_EXPOSURE_UNITS,
    PaperTradingService,
)


def _mock_db_with_exposure(exposure: Decimal | float = 0):
    """Construye un mock de AsyncSession donde el SUM(stake_units) devuelve `exposure`."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    exposure_result = MagicMock()
    exposure_result.scalar_one = MagicMock(return_value=Decimal(str(exposure)))
    db.execute = AsyncMock(return_value=exposure_result)
    return db


@pytest.mark.asyncio
async def test_record_value_bet_applies_fractional_kelly():
    """Paper aplica 1/4 Kelly al `kelly_full` para replicar staking real."""
    svc = PaperTradingService()
    db = _mock_db_with_exposure(0)

    vb = ValueBet(
        outcome_index=0,
        outcome_key="burnley",
        bookmaker_key="coolbet",
        bookmaker_odds=7.7,
        consensus_prob=0.1316,
        implied_prob=0.1299,
        value_pct=0.0134,
        kelly_full=0.008,  # 0.8% full → 0.2% con 1/4
        edge_confidence="reference",
    )
    opp = MagicMock(id=42, outcome_id=1, bookmaker_id=2)

    paper = await svc.record_value_bet(db, opp, vb, match_id=10)
    assert paper.source_type == "value"
    assert paper.opportunity_id == 42
    assert paper.match_id == 10
    assert paper.odds_taken == Decimal("7.7")
    assert paper.stake_units == Decimal("0.008") * PAPER_KELLY_FRACTION
    assert paper.ev_at_placement == Decimal("0.0134")


@pytest.mark.asyncio
async def test_record_value_bet_caps_at_max_stake():
    """Kelly muy alto (señal fuerte) se capea a PAPER_MAX_STAKE_UNITS."""
    svc = PaperTradingService()
    db = _mock_db_with_exposure(0)

    # kelly_full 0.30 × 0.25 = 0.075 → debe capearse a 0.05
    vb = ValueBet(
        outcome_index=0, outcome_key="x", bookmaker_key="x",
        bookmaker_odds=3.0, consensus_prob=0.50, implied_prob=0.333,
        value_pct=0.5, kelly_full=0.30, edge_confidence="high",
    )
    opp = MagicMock(id=1, outcome_id=1, bookmaker_id=1)
    paper = await svc.record_value_bet(db, opp, vb, match_id=1)
    assert paper.stake_units == PAPER_MAX_STAKE_UNITS


@pytest.mark.asyncio
async def test_record_value_bet_falls_back_to_default_stake_when_kelly_zero():
    svc = PaperTradingService()
    db = _mock_db_with_exposure(0)

    vb = ValueBet(
        outcome_index=0, outcome_key="x", bookmaker_key="x",
        bookmaker_odds=2.0, consensus_prob=0.5, implied_prob=0.5,
        value_pct=0.01, kelly_full=0.0, edge_confidence="reference",
    )
    opp = MagicMock(id=1, outcome_id=1, bookmaker_id=1)
    paper = await svc.record_value_bet(db, opp, vb, match_id=1)
    assert paper.stake_units == DEFAULT_STAKE_UNITS


@pytest.mark.asyncio
async def test_record_value_bet_skips_when_exposure_cap_full():
    """Si el cap de exposición ya está saturado, devuelve None sin registrar."""
    svc = PaperTradingService()
    db = _mock_db_with_exposure(PAPER_MAX_TOTAL_EXPOSURE_UNITS)

    vb = ValueBet(
        outcome_index=0, outcome_key="x", bookmaker_key="x",
        bookmaker_odds=2.5, consensus_prob=0.45, implied_prob=0.40,
        value_pct=0.05, kelly_full=0.04, edge_confidence="medium",
    )
    opp = MagicMock(id=1, outcome_id=1, bookmaker_id=1)
    paper = await svc.record_value_bet(db, opp, vb, match_id=1)
    assert paper is None
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_record_value_bet_scales_to_remaining_budget():
    """Si queda menos cap del que pide Kelly, se scalea al disponible."""
    svc = PaperTradingService()
    # Ya hay 18% expuesto, quedan 2% disponibles
    db = _mock_db_with_exposure(Decimal("0.18"))

    # kelly_full 0.20 × 0.25 = 0.05 → desired = 0.05 (cap por bet)
    # available = 0.20 - 0.18 = 0.02 → stake = 0.02
    vb = ValueBet(
        outcome_index=0, outcome_key="x", bookmaker_key="x",
        bookmaker_odds=2.5, consensus_prob=0.45, implied_prob=0.40,
        value_pct=0.05, kelly_full=0.20, edge_confidence="medium",
    )
    opp = MagicMock(id=1, outcome_id=1, bookmaker_id=1)
    paper = await svc.record_value_bet(db, opp, vb, match_id=1)
    assert paper is not None
    assert paper.stake_units == Decimal("0.02")


@pytest.mark.asyncio
async def test_settle_match_missing_scores_returns_zero():
    svc = PaperTradingService()
    db = MagicMock()
    match = MagicMock(home_score=None, away_score=None, id=1)
    result = await svc.settle_match(db, match)
    assert result == {"settled": 0, "skipped": 0}


class TestSettlement:
    """Tests de cálculo de profit con DB mock controlado."""

    def _make_row(self, outcome_key: str, odds: str, stake: str, market_type_key: str = "h2h", parameter=None, commission: str | None = None):
        paper = MagicMock()
        paper.result = "pending"
        paper.odds_taken = Decimal(odds)
        paper.stake_units = Decimal(stake)
        paper.profit_units = None
        paper.resolved_at = None
        paper.commission_pct = Decimal(commission) if commission is not None else None
        outcome = MagicMock()
        outcome.key = outcome_key
        market = MagicMock()
        market.parameter = parameter
        market_type = MagicMock()
        market_type.key = market_type_key
        return paper, outcome, market, market_type

    def _mock_db(self, rows, home_name="Burnley", away_name="Nottingham Forest"):
        db = MagicMock()
        db.execute = AsyncMock()
        home_team = MagicMock(canonical_name=home_name)
        away_team = MagicMock(canonical_name=away_name)
        team_result1, team_result2, pending_result = MagicMock(), MagicMock(), MagicMock()
        team_result1.scalar_one.return_value = home_team
        team_result2.scalar_one.return_value = away_team
        pending_result.all.return_value = rows
        db.execute.side_effect = [team_result1, team_result2, pending_result]
        return db

    @pytest.mark.asyncio
    async def test_home_win_settles_home_bet_as_won(self):
        svc = PaperTradingService()
        paper_home, *rest_h = self._make_row("burnley", "7.7", "0.002")
        paper_away, *rest_a = self._make_row("nottingham_forest", "1.49", "0.002")
        db = self._mock_db([(paper_home, *rest_h), (paper_away, *rest_a)])

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
        paper_draw, *rest_d = self._make_row("draw", "3.5", "0.01")
        paper_home, *rest_h = self._make_row("burnley", "7.7", "0.01")
        db = self._mock_db([(paper_draw, *rest_d), (paper_home, *rest_h)])

        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=1, away_score=1)
        await svc.settle_match(db, match)

        assert paper_draw.result == "won"
        assert paper_home.result == "lost"

    @pytest.mark.asyncio
    async def test_totals_over_wins_when_total_exceeds_line(self):
        svc = PaperTradingService()
        paper_over, *rest_o = self._make_row("over", "2.0", "0.5", "totals", Decimal("8.5"))
        paper_under, *rest_u = self._make_row("under", "2.0", "0.5", "totals", Decimal("8.5"))
        db = self._mock_db([(paper_over, *rest_o), (paper_under, *rest_u)])

        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=8, away_score=6)
        r = await svc.settle_match(db, match)

        assert r["settled"] == 2
        assert paper_over.result == "won"
        assert paper_over.profit_units == Decimal("0.5") * (Decimal("2.0") - Decimal("1"))
        assert paper_under.result == "lost"
        assert paper_under.profit_units == -Decimal("0.5")

    @pytest.mark.asyncio
    async def test_totals_under_wins_when_total_below_line(self):
        svc = PaperTradingService()
        paper_over, *rest_o = self._make_row("over", "2.0", "0.5", "totals", Decimal("7.5"))
        paper_under, *rest_u = self._make_row("under", "2.0", "0.5", "totals", Decimal("7.5"))
        db = self._mock_db([(paper_over, *rest_o), (paper_under, *rest_u)])

        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=2, away_score=5)
        await svc.settle_match(db, match)

        assert paper_over.result == "lost"
        assert paper_under.result == "won"

    @pytest.mark.asyncio
    async def test_totals_push_on_exact_line(self):
        svc = PaperTradingService()
        paper_over, *rest_o = self._make_row("over", "2.0", "0.5", "totals", Decimal("8"))
        paper_under, *rest_u = self._make_row("under", "2.0", "0.5", "totals", Decimal("8"))
        db = self._mock_db([(paper_over, *rest_o), (paper_under, *rest_u)])

        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=5, away_score=3)
        await svc.settle_match(db, match)

        assert paper_over.result == "void"
        assert paper_over.profit_units == Decimal("0")
        assert paper_under.result == "void"

    @pytest.mark.asyncio
    async def test_unsupported_market_is_skipped(self):
        svc = PaperTradingService()
        paper, *rest = self._make_row("home", "2.0", "0.5", "spreads", Decimal("1.5"))
        db = self._mock_db([(paper, *rest)])

        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=3, away_score=1)
        r = await svc.settle_match(db, match)

        assert r == {"settled": 0, "skipped": 1}
        assert paper.result == "pending"
        assert paper.profit_units is None

    @pytest.mark.asyncio
    async def test_won_applies_commission_when_snapshotted(self):
        """Commission is deducted from profit on `won`, mirroring the arb detector."""
        svc = PaperTradingService()
        # Pinnacle via SportMarket: 1% commission on net winnings
        paper_won, *rest_w = self._make_row("burnley", "2.0", "1.0", commission="0.01")
        db = self._mock_db([(paper_won, *rest_w)])

        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=2, away_score=0)
        await svc.settle_match(db, match)

        assert paper_won.result == "won"
        # gross = 1.0 * (2.0 - 1) = 1.0; net = 1.0 * (1 - 0.01) = 0.99
        assert paper_won.profit_units == Decimal("1.0") * (Decimal("2.0") - Decimal("1")) * (Decimal("1") - Decimal("0.01"))

    @pytest.mark.asyncio
    async def test_lost_ignores_commission(self):
        """A losing bet loses the full stake regardless of commission."""
        svc = PaperTradingService()
        paper_lost, *rest_l = self._make_row("nottingham_forest", "1.5", "0.5", commission="0.01")
        db = self._mock_db([(paper_lost, *rest_l)])

        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=2, away_score=0)
        await svc.settle_match(db, match)

        assert paper_lost.result == "lost"
        assert paper_lost.profit_units == -Decimal("0.5")

    @pytest.mark.asyncio
    async def test_won_without_commission_uses_full_profit(self):
        """Back-compat: paper bets without commission_pct (legacy rows) settle as before."""
        svc = PaperTradingService()
        paper_won, *rest_w = self._make_row("burnley", "2.0", "1.0", commission=None)
        db = self._mock_db([(paper_won, *rest_w)])

        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=2, away_score=0)
        await svc.settle_match(db, match)

        assert paper_won.profit_units == Decimal("1.0") * (Decimal("2.0") - Decimal("1"))

    # --- Regresión: keys posicionales h2h ('home'/'away'/'draw') ---
    # Bug: el normalizador canoniza algunos outcomes h2h a 'home'/'away', pero
    # el settlement comparaba la key contra el slug del nombre del equipo
    # (p.ej. 'washington_nationals'), por lo que NINGUNA leg matcheaba y AMBAS
    # se liquidaban 'lost'. Afectó arb groups 152/153/155/156 (ROI −3.01% vs
    # +2.19% real). El fix hace que settle entienda ambas convenciones.

    @pytest.mark.asyncio
    async def test_h2h_positional_away_key_settles_as_won(self):
        """Visitante gana 0-2: la leg con key 'away' debe ganar, no perder."""
        svc = PaperTradingService()
        paper_home, *rest_h = self._make_row("home", "2.10", "0.5")
        paper_away, *rest_a = self._make_row("away", "2.05", "0.5")
        db = self._mock_db(
            [(paper_home, *rest_h), (paper_away, *rest_a)],
            home_name="Atlanta Braves",
            away_name="Washington Nationals",
        )
        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=0, away_score=2)
        r = await svc.settle_match(db, match)

        assert r["settled"] == 2
        assert paper_away.result == "won"
        assert paper_home.result == "lost"
        # un arb de 2 vías NUNCA puede tener ambas legs perdidas
        assert {paper_home.result, paper_away.result} == {"won", "lost"}

    @pytest.mark.asyncio
    async def test_h2h_positional_home_key_settles_as_won(self):
        """Local gana 120-108: la leg con key 'home' debe ganar."""
        svc = PaperTradingService()
        paper_home, *rest_h = self._make_row("home", "1.80", "0.5")
        paper_away, *rest_a = self._make_row("away", "2.30", "0.5")
        db = self._mock_db(
            [(paper_home, *rest_h), (paper_away, *rest_a)],
            home_name="San Antonio Spurs",
            away_name="Oklahoma City Thunder",
        )
        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=120, away_score=108)
        await svc.settle_match(db, match)

        assert paper_home.result == "won"
        assert paper_away.result == "lost"

    @pytest.mark.asyncio
    async def test_h2h_unknown_key_is_skipped_not_lost(self):
        """Una key h2h que no corresponde a ningún lado queda 'pending' (skip),
        nunca 'lost' por defecto — para no corromper ambas legs de un arb."""
        svc = PaperTradingService()
        paper, *rest = self._make_row("equipo_inexistente", "2.0", "0.5")
        db = self._mock_db(
            [(paper, *rest)],
            home_name="Atlanta Braves",
            away_name="Washington Nationals",
        )
        match = MagicMock(id=1, home_team_id=10, away_team_id=20, home_score=0, away_score=2)
        r = await svc.settle_match(db, match)

        assert r == {"settled": 0, "skipped": 1}
        assert paper.result == "pending"
        assert paper.profit_units is None
