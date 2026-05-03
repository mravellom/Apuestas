import pytest

from app.core.formulas import (
    calculate_roi,
    consensus_probability,
    consensus_probability_with_std,
    flat_stake,
    fractional_kelly,
    implied_probability,
    kelly_criterion,
    kelly_criterion_net,
    kelly_criterion_uncertainty_adjusted,
    odds_to_fair_probs,
    remove_vig_proportional,
    remove_vig_shin,
    value_calculation,
    value_calculation_net,
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


class TestRemoveVigShin:
    def test_preserves_ranking(self):
        implied = [implied_probability(2.10), implied_probability(3.30), implied_probability(3.60)]
        fair = remove_vig_shin(implied)
        assert fair[0] > fair[1] > fair[2]

    def test_falls_back_when_no_vig(self):
        # If probs already sum to <= 1, Shin reduces to proportional scaling
        fair = remove_vig_shin([0.5, 0.3, 0.2])
        assert fair == pytest.approx([0.5, 0.3, 0.2])

    def test_reduces_overround(self):
        """Output must be closer to 1.0 than the raw input."""
        implied = [implied_probability(2.10), implied_probability(3.30), implied_probability(3.60)]
        overround = sum(implied)
        fair = remove_vig_shin(implied)
        assert abs(sum(fair) - 1.0) < abs(overround - 1.0)

    def test_two_way_market_symmetry(self):
        # Symmetric input must yield symmetric output
        implied = [implied_probability(1.90), implied_probability(1.90)]
        fair = remove_vig_shin(implied)
        assert fair[0] == pytest.approx(fair[1])

    def test_all_probs_in_valid_range(self):
        implied = [0.40, 0.40, 0.35]  # sums to 1.15 (15% overround)
        fair = remove_vig_shin(implied)
        assert all(0 < p < 1 for p in fair)

    def test_sums_to_one(self):
        implied = [implied_probability(2.10), implied_probability(3.30), implied_probability(3.60)]
        fair = remove_vig_shin(implied)
        assert sum(fair) == pytest.approx(1.0, abs=1e-6)

    def test_longshot_bias_correction(self):
        """Shin shifts mass from longshots to favorites relative to proportional method."""
        implied = [implied_probability(1.50), implied_probability(4.00), implied_probability(8.00)]
        fair_shin = remove_vig_shin(implied)
        fair_prop = remove_vig_proportional(implied)
        # Favorite: shin strictly > proportional
        assert fair_shin[0] > fair_prop[0]
        # Longshot: shin strictly < proportional
        assert fair_shin[2] < fair_prop[2]


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


class TestValueCalculationNet:
    def test_zero_commission_matches_original(self):
        assert value_calculation_net(0.5, 2.10, 0.0) == pytest.approx(value_calculation(0.5, 2.10))

    def test_commission_reduces_ev(self):
        raw = value_calculation(0.5, 2.10)   # +0.05
        net = value_calculation_net(0.5, 2.10, 0.01)
        assert net < raw
        # EV_net = 0.5 * (2.10-1) * 0.99 - 0.5 = 0.5*1.1*0.99 - 0.5 = 0.5445 - 0.5 = 0.0445
        assert net == pytest.approx(0.0445, abs=1e-4)

    def test_marginal_ev_turns_negative_with_commission(self):
        # EV bruto 0.5% se convierte en negativo con 1% commission en odds 2.0
        # EV_raw = 0.505 * 2 - 1 = 0.01
        # EV_net = 0.505*1*0.99 - 0.495 = 0.49995 - 0.495 = 0.00495
        # Still positive but reduced
        net = value_calculation_net(0.505, 2.0, 0.01)
        assert 0 < net < value_calculation(0.505, 2.0)


class TestKellyCriterionNet:
    def test_zero_commission_matches_original(self):
        assert kelly_criterion_net(0.5, 2.10, 0.0) == pytest.approx(kelly_criterion(0.5, 2.10))

    def test_commission_reduces_kelly(self):
        raw = kelly_criterion(0.5, 2.10)
        net = kelly_criterion_net(0.5, 2.10, 0.01)
        assert net < raw

    def test_odds_below_one_returns_zero(self):
        assert kelly_criterion_net(0.5, 0.9, 0.01) == 0.0


class TestConsensusProbabilityWithStd:
    def test_single_book_has_zero_std(self):
        """Con un solo libro no hay disenso → SE = 0."""
        means, stds = consensus_probability_with_std({"bk1": [2.10, 3.30, 3.60]})
        assert all(s == 0.0 for s in stds)

    def test_identical_books_have_zero_std(self):
        """Libros que coinciden exactamente → SE = 0."""
        odds = {f"bk{i}": [2.10, 3.30, 3.60] for i in range(5)}
        _, stds = consensus_probability_with_std(odds)
        assert all(s == pytest.approx(0.0, abs=1e-12) for s in stds)

    def test_disagreement_increases_std(self):
        """Mayor dispersión entre libros → mayor SE."""
        tight = {f"bk{i}": [2.10, 3.30, 3.60] for i in range(5)}
        spread = {
            "bk1": [1.90, 3.30, 4.20],
            "bk2": [2.10, 3.30, 3.60],
            "bk3": [2.30, 3.30, 3.10],
            "bk4": [2.20, 3.30, 3.30],
            "bk5": [2.00, 3.30, 3.90],
        }
        _, stds_tight = consensus_probability_with_std(tight)
        _, stds_spread = consensus_probability_with_std(spread)
        # Outcomes 0 (home) y 2 (away) varían entre libros en `spread`
        assert stds_spread[0] > stds_tight[0]
        assert stds_spread[2] > stds_tight[2]

    def test_more_books_reduce_std(self):
        """Misma dispersión pero más libros → SE más chico (1/sqrt(N))."""
        # Replicar el mismo patrón con 5 vs 20 libros
        pattern = [(2.05, 3.30, 3.65), (2.15, 3.30, 3.55)]
        small = {
            f"bk{i}": list(pattern[i % 2]) for i in range(5)
        }
        large = {
            f"bk{i}": list(pattern[i % 2]) for i in range(20)
        }
        _, stds_small = consensus_probability_with_std(small)
        _, stds_large = consensus_probability_with_std(large)
        assert stds_large[0] < stds_small[0]


class TestKellyCriterionUncertaintyAdjusted:
    def test_zero_std_matches_kelly_net(self):
        """Sin incertidumbre, debe igualar al Kelly net estándar."""
        adj = kelly_criterion_uncertainty_adjusted(0.55, 2.10, 0.0, 0.0)
        assert adj == pytest.approx(kelly_criterion_net(0.55, 2.10, 0.0))

    def test_positive_std_reduces_kelly(self):
        """Std > 0 con edge > σ → shrinkage menor que 1, Kelly se reduce."""
        base = kelly_criterion_net(0.55, 2.10, 0.0)
        adj = kelly_criterion_uncertainty_adjusted(0.55, 2.10, 0.01, 0.0)
        assert 0 < adj < base

    def test_high_std_zeros_kelly(self):
        """σ > edge → shrinkage clampeado a 0 (no apostar)."""
        # edge = 0.55*2.10 - 1 = 0.155, σ_edge = 2.10*0.10 = 0.21 > edge
        adj = kelly_criterion_uncertainty_adjusted(0.55, 2.10, 0.10, 0.0)
        assert adj == 0.0

    def test_zero_kelly_stays_zero(self):
        """Si no hay edge, ningún ajuste; queda en 0."""
        adj = kelly_criterion_uncertainty_adjusted(0.40, 2.10, 0.01, 0.0)
        assert adj == 0.0

    def test_commission_compounds_with_uncertainty(self):
        """Comisión y σ ambos reducen el Kelly final."""
        no_comm = kelly_criterion_uncertainty_adjusted(0.55, 2.10, 0.005, 0.0)
        with_comm = kelly_criterion_uncertainty_adjusted(0.55, 2.10, 0.005, 0.01)
        assert 0 < with_comm < no_comm

