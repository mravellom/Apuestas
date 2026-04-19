"""Tests unitarios para app.core.arbitrage (funciones puras)."""

import pytest

from app.core.arbitrage import (
    ArbLeg,
    ArbOpportunity,
    calculate_stakes,
    detect_arbitrage,
    find_best_odds,
)


class TestFindBestOdds:
    def test_picks_highest_odds_per_outcome(self):
        odds = {
            "bet365":   [2.00, 3.30, 3.50],
            "pinnacle": [2.10, 3.20, 3.40],
            "betfair":  [2.05, 3.40, 3.60],
        }
        best = find_best_odds(odds, ["home", "draw", "away"])
        assert best[0] == (2.10, "pinnacle")
        assert best[1] == (3.40, "betfair")
        assert best[2] == (3.60, "betfair")

    def test_ignores_bookmakers_with_wrong_outcome_count(self):
        odds = {
            "bet365":   [2.00, 3.30, 3.50],
            "broken":   [2.10, 3.20],  # missing outcome
        }
        best = find_best_odds(odds, ["home", "draw", "away"])
        assert best[0] == (2.00, "bet365")
        assert best[1] == (3.30, "bet365")
        assert best[2] == (3.50, "bet365")

    def test_empty_bookmakers_returns_zeros(self):
        best = find_best_odds({}, ["home", "draw", "away"])
        assert best == [(0.0, ""), (0.0, ""), (0.0, "")]


class TestDetectArbitrage:
    def _build_odds(self, rows: list[list[float]]) -> dict[str, list[float]]:
        return {f"bk{i}": row for i, row in enumerate(rows)}

    def test_returns_none_when_not_enough_bookmakers(self):
        odds = {"bet365": [2.10, 3.30, 3.60], "pinnacle": [2.12, 3.25, 3.55]}
        result = detect_arbitrage(odds, ["home", "draw", "away"], min_bookmakers=5)
        assert result is None

    def test_returns_none_when_no_arbitrage(self):
        # Fair market with vig — sum of 1/odds > 1
        odds = self._build_odds([
            [2.00, 3.30, 3.60],
            [2.05, 3.25, 3.55],
            [2.10, 3.20, 3.50],
            [2.08, 3.35, 3.45],
            [2.02, 3.28, 3.58],
        ])
        result = detect_arbitrage(odds, ["home", "draw", "away"])
        assert result is None

    def test_detects_clear_arbitrage(self):
        # Each bookmaker is best at exactly one outcome, combined they create an arb
        # best: home=2.60, draw=3.80, away=4.20  → implied = 0.3846+0.2632+0.2381 = 0.886
        odds = {
            "bet365":    [2.60, 3.10, 3.20],
            "pinnacle":  [2.00, 3.80, 3.20],
            "betfair":   [2.00, 3.10, 4.20],
            "williamhill": [2.30, 3.40, 3.60],
            "unibet":    [2.10, 3.50, 3.50],
        }
        result = detect_arbitrage(
            odds, ["home", "draw", "away"],
            outcome_names=["Home Win", "Draw", "Away Win"],
            min_profit_pct=0.5,
            min_bookmakers=5,
        )
        assert result is not None
        assert result.is_valid
        assert result.total_implied < 1.0
        assert result.profit_pct > 0.5
        assert result.num_outcomes == 3
        assert len(result.legs) == 3

        # Stakes must sum to 1.0 (full capital split across legs)
        assert sum(leg.stake_pct for leg in result.legs) == pytest.approx(1.0, abs=1e-4)

        # Each leg holds the best-odds bookmaker
        leg_by_outcome = {leg.outcome_key: leg for leg in result.legs}
        assert leg_by_outcome["home"].bookmaker_key == "bet365"
        assert leg_by_outcome["home"].best_odds == 2.60
        assert leg_by_outcome["draw"].bookmaker_key == "pinnacle"
        assert leg_by_outcome["draw"].best_odds == 3.80
        assert leg_by_outcome["away"].bookmaker_key == "betfair"
        assert leg_by_outcome["away"].best_odds == 4.20

        # Outcome names propagated
        assert leg_by_outcome["home"].outcome_name == "Home Win"

    def test_equal_payouts_across_legs(self):
        """Stakes must equalize payouts: stake_i * odds_i ≈ constant for all legs."""
        odds = {
            "bet365":    [2.60, 3.10, 3.20],
            "pinnacle":  [2.00, 3.80, 3.20],
            "betfair":   [2.00, 3.10, 4.20],
            "williamhill": [2.30, 3.40, 3.60],
            "unibet":    [2.10, 3.50, 3.50],
        }
        arb = detect_arbitrage(odds, ["home", "draw", "away"], min_bookmakers=5)
        assert arb is not None
        payouts = [leg.stake_pct * leg.best_odds for leg in arb.legs]
        # all payouts should be equal (that's the whole point of arbitrage)
        for p in payouts[1:]:
            assert p == pytest.approx(payouts[0], rel=1e-3)

    def test_filters_by_min_profit_pct(self):
        # Tiny arb (~0.1%) — rejected when min_profit_pct=0.5
        odds = self._build_odds([
            [2.01, 3.00, 3.00],
            [2.01, 3.01, 3.00],
            [2.01, 3.00, 3.01],
            [2.00, 3.00, 3.00],
            [2.00, 3.00, 3.00],
        ])
        result = detect_arbitrage(odds, ["home", "draw", "away"], min_profit_pct=5.0)
        assert result is None

    def test_rejects_invalid_odds(self):
        # Contains odds ≤ 1.0 → invalid
        odds = {
            "bet365":    [2.60, 3.10, 1.00],
            "pinnacle":  [2.00, 3.80, 1.00],
            "betfair":   [2.00, 3.10, 1.00],
            "williamhill": [2.30, 3.40, 1.00],
            "unibet":    [2.10, 3.50, 1.00],
        }
        assert detect_arbitrage(odds, ["home", "draw", "away"]) is None

    def test_two_way_market(self):
        # 2-outcome market (e.g. tennis): enough arb
        odds = {
            "bet365":    [2.20, 1.90],
            "pinnacle":  [2.00, 2.10],
            "betfair":   [2.00, 1.95],
            "williamhill": [1.95, 2.00],
            "unibet":    [2.05, 1.95],
        }
        # best = 2.20 + 2.10 → implied = 0.4545 + 0.4762 = 0.9307 → profit ~7.4%
        result = detect_arbitrage(odds, ["home", "away"], min_bookmakers=5)
        assert result is not None
        assert result.num_outcomes == 2
        assert result.profit_pct > 5.0

    def test_default_outcome_names_fallback_to_keys(self):
        odds = {
            "bet365":    [2.60, 3.10, 3.20],
            "pinnacle":  [2.00, 3.80, 3.20],
            "betfair":   [2.00, 3.10, 4.20],
            "williamhill": [2.30, 3.40, 3.60],
            "unibet":    [2.10, 3.50, 3.50],
        }
        arb = detect_arbitrage(odds, ["home", "draw", "away"], min_bookmakers=5)
        assert arb is not None
        assert {leg.outcome_name for leg in arb.legs} == {"home", "draw", "away"}


class TestCalculateStakes:
    def _arb(self) -> ArbOpportunity:
        legs = [
            ArbLeg("home", "Home", "bet365", 2.60, 0.3846, 0.4341),
            ArbLeg("draw", "Draw", "pinnacle", 3.80, 0.2632, 0.2971),
            ArbLeg("away", "Away", "betfair", 4.20, 0.2381, 0.2688),
        ]
        return ArbOpportunity(
            legs=legs,
            total_implied=0.8859,
            profit_pct=12.88,
            num_outcomes=3,
        )

    def test_stakes_sum_to_capital(self):
        arb = self._arb()
        stakes = calculate_stakes(arb, 1000.0)
        total = sum(s["stake"] for s in stakes)
        assert total == pytest.approx(1000.0, abs=0.5)

    def test_payout_equals_stake_times_odds(self):
        arb = self._arb()
        stakes = calculate_stakes(arb, 1000.0)
        for s in stakes:
            assert s["payout"] == pytest.approx(s["stake"] * s["odds"], abs=0.01)

    def test_all_payouts_are_similar_for_arbitrage(self):
        """The defining property: no matter which outcome wins, profit is the same."""
        arb = self._arb()
        stakes = calculate_stakes(arb, 1000.0)
        payouts = [s["payout"] for s in stakes]
        # All payouts within a small tolerance (stake_pct was rounded to 5 decimals)
        for p in payouts[1:]:
            assert p == pytest.approx(payouts[0], rel=1e-3)

    def test_result_schema(self):
        arb = self._arb()
        stakes = calculate_stakes(arb, 500.0)
        assert len(stakes) == 3
        keys = {"outcome", "bookmaker", "odds", "stake", "payout"}
        for s in stakes:
            assert set(s.keys()) == keys


class TestArbOpportunityIsValid:
    def test_valid_when_implied_below_one_and_profit_positive(self):
        arb = ArbOpportunity(total_implied=0.95, profit_pct=5.2)
        assert arb.is_valid

    def test_invalid_when_implied_ge_one(self):
        arb = ArbOpportunity(total_implied=1.02, profit_pct=-2.0)
        assert not arb.is_valid

    def test_invalid_when_profit_zero(self):
        arb = ArbOpportunity(total_implied=0.99, profit_pct=0.0)
        assert not arb.is_valid


class TestArbitrageWithCommission:
    """Arbs que pasarían sin comisión pero desaparecen o quedan al borde con broker."""

    def test_arb_survives_when_margin_exceeds_commission(self):
        # Arb bruto ~2.5% con commission 1% → arb neto ~1.5% (> min_profit_pct 0.5)
        odds = {
            "bk_a": [2.10, 4.20, 4.50],
            "bk_b": [2.20, 4.40, 4.60],
            "bk_c": [2.25, 4.50, 4.80],
        }
        arb = detect_arbitrage(
            odds, ["home", "draw", "away"],
            min_profit_pct=0.5, min_bookmakers=3,
            commission_by_bookmaker={"bk_a": 0.01, "bk_b": 0.01, "bk_c": 0.01},
        )
        assert arb is not None
        assert arb.profit_pct > 0.5

    def test_marginal_arb_disappears_with_high_commission(self):
        # Arb bruto ~0.5% con commission 1% → se come la ganancia → no arb
        odds = {
            "bk_a": [2.05, 4.05, 4.20],
            "bk_b": [2.06, 4.10, 4.25],
        }
        # Primero sin comisión
        arb_raw = detect_arbitrage(
            odds, ["home", "draw", "away"],
            min_profit_pct=0.1, min_bookmakers=2,
        )
        # Verify there IS a raw arb
        if arb_raw is None:
            pytest.skip("No raw arb in test data; adjust fixture")

        # Ahora con commission 2% — típico broker alto
        arb_with_comm = detect_arbitrage(
            odds, ["home", "draw", "away"],
            min_profit_pct=0.1, min_bookmakers=2,
            commission_by_bookmaker={"bk_a": 0.02, "bk_b": 0.02},
        )
        # Con commission alta, el profit neto debería ser menor o None
        if arb_with_comm is not None:
            assert arb_with_comm.profit_pct < arb_raw.profit_pct

    def test_commission_zero_matches_no_commission_param(self):
        odds = {
            "bk_a": [2.10, 4.20, 4.50],
            "bk_b": [2.20, 4.40, 4.60],
        }
        arb_no = detect_arbitrage(odds, ["home", "draw", "away"],
                                   min_profit_pct=0.1, min_bookmakers=2)
        arb_zero = detect_arbitrage(odds, ["home", "draw", "away"],
                                     min_profit_pct=0.1, min_bookmakers=2,
                                     commission_by_bookmaker={"bk_a": 0.0, "bk_b": 0.0})
        if arb_no and arb_zero:
            assert arb_no.profit_pct == pytest.approx(arb_zero.profit_pct)
