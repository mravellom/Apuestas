import pytest

from app.core.formulas import (
    calculate_roi,
    consensus_probability,
    flat_stake,
    fractional_kelly,
    implied_probability,
    kelly_criterion,
    odds_to_fair_probs,
    remove_vig_proportional,
    value_calculation,
)


class TestImpliedProbability:
    def test_basic(self):
        assert implied_probability(2.0) == pytest.approx(0.5)

    def test_favorite(self):
        assert implied_probability(1.5) == pytest.approx(0.6667, rel=1e-3)

    def test_underdog(self):
        assert implied_probability(5.0) == pytest.approx(0.2)

    def test_invalid_odds(self):
        with pytest.raises(ValueError):
            implied_probability(0)
        with pytest.raises(ValueError):
            implied_probability(-1.5)


class TestRemoveVig:
    def test_1x2_market(self):
        # Cuotas típicas de 1X2: Home=2.10, Draw=3.30, Away=3.60
        implied = [implied_probability(2.10), implied_probability(3.30), implied_probability(3.60)]
        fair = remove_vig_proportional(implied)
        assert sum(fair) == pytest.approx(1.0, abs=1e-10)
        assert fair[0] > fair[1] > fair[2]

    def test_no_vig(self):
        # Si no hay vig (probs suman 1), no cambia
        fair = remove_vig_proportional([0.5, 0.3, 0.2])
        assert fair == pytest.approx([0.5, 0.3, 0.2])


class TestOddsToFairProbs:
    def test_two_way(self):
        fair = odds_to_fair_probs([1.90, 1.90])
        assert len(fair) == 2
        assert fair[0] == pytest.approx(0.5)
        assert sum(fair) == pytest.approx(1.0)

    def test_three_way(self):
        fair = odds_to_fair_probs([2.10, 3.30, 3.60])
        assert sum(fair) == pytest.approx(1.0)


class TestValueCalculation:
    def test_positive_value(self):
        # Prob real 45%, cuota 2.40 -> EV = 0.45*2.40 - 1 = 0.08
        assert value_calculation(0.45, 2.40) == pytest.approx(0.08)

    def test_no_value(self):
        # Prob real 40%, cuota 2.40 -> EV = 0.40*2.40 - 1 = -0.04
        assert value_calculation(0.40, 2.40) == pytest.approx(-0.04)

    def test_fair_odds(self):
        # Prob real 50%, cuota 2.00 -> EV = 0
        assert value_calculation(0.50, 2.00) == pytest.approx(0.0)


class TestKellyCriterion:
    def test_basic(self):
        # odds=2.40, p=0.45 -> b=1.40, f=(1.40*0.45-0.55)/1.40 = 0.0571
        result = kelly_criterion(0.45, 2.40)
        assert result == pytest.approx(0.0571, rel=1e-2)

    def test_no_edge(self):
        # odds=2.00, p=0.50 -> f=(1.0*0.5-0.5)/1.0 = 0
        assert kelly_criterion(0.50, 2.00) == pytest.approx(0.0)

    def test_negative_edge(self):
        # No debería apostar si no hay edge
        assert kelly_criterion(0.30, 2.00) == 0.0

    def test_odds_lte_1(self):
        assert kelly_criterion(0.90, 1.0) == 0.0


class TestFractionalKelly:
    def test_quarter_kelly(self):
        full = kelly_criterion(0.45, 2.40)
        frac = fractional_kelly(0.45, 2.40, 0.25)
        assert frac == pytest.approx(full * 0.25)

    def test_half_kelly(self):
        full = kelly_criterion(0.45, 2.40)
        frac = fractional_kelly(0.45, 2.40, 0.50)
        assert frac == pytest.approx(full * 0.50)


class TestFlatStake:
    def test_default(self):
        assert flat_stake(1000) == pytest.approx(20.0)

    def test_custom_pct(self):
        assert flat_stake(1000, 0.05) == pytest.approx(50.0)


class TestConsensusProbability:
    def test_single_bookmaker(self):
        odds = {"bet365": [2.10, 3.30, 3.60]}
        probs = consensus_probability(odds)
        assert sum(probs) == pytest.approx(1.0)

    def test_multiple_bookmakers(self):
        odds = {
            "bet365": [2.10, 3.30, 3.60],
            "pinnacle": [2.12, 3.25, 3.55],
            "betfair": [2.05, 3.40, 3.50],
        }
        probs = consensus_probability(odds)
        assert sum(probs) == pytest.approx(1.0)
        assert len(probs) == 3

    def test_sharp_weighting(self):
        odds = {
            "bet365": [2.10, 3.30, 3.60],
            "pinnacle": [2.20, 3.10, 3.40],
        }
        probs_no_sharp = consensus_probability(odds)
        probs_sharp = consensus_probability(odds, sharp_bookmakers={"pinnacle"})
        # Pinnacle has higher home odds (lower prob), so sharp-weighted home prob should be lower
        assert probs_sharp[0] < probs_no_sharp[0] or probs_sharp[0] == pytest.approx(
            probs_no_sharp[0], abs=0.01
        )

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            consensus_probability({})


class TestROI:
    def test_positive(self):
        assert calculate_roi(350, 5000) == pytest.approx(7.0)

    def test_negative(self):
        assert calculate_roi(-200, 5000) == pytest.approx(-4.0)

    def test_zero_staked(self):
        assert calculate_roi(100, 0) == 0.0
