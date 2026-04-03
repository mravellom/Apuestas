import pytest

from app.core.staking.factory import get_strategy
from app.core.staking.flat import FlatStrategy
from app.core.staking.kelly import FractionalKellyStrategy, KellyStrategy


class TestKellyStrategy:
    def test_basic_stake(self):
        strategy = KellyStrategy()
        stake = strategy.calculate_stake(bankroll=1000, odds=2.40, probability=0.45)
        assert stake > 0
        assert stake <= 1000 * 0.05  # respects max_stake_pct

    def test_no_edge_zero_stake(self):
        strategy = KellyStrategy()
        stake = strategy.calculate_stake(bankroll=1000, odds=2.00, probability=0.50)
        assert stake == 0.0

    def test_max_stake_cap(self):
        strategy = KellyStrategy()
        # Very high edge should be capped
        stake = strategy.calculate_stake(bankroll=1000, odds=5.0, probability=0.80, max_stake_pct=0.05)
        assert stake == 50.0  # 5% of 1000


class TestFractionalKellyStrategy:
    def test_quarter_kelly(self):
        full = KellyStrategy()
        frac = FractionalKellyStrategy(fraction=0.25)
        full_stake = full.calculate_stake(bankroll=1000, odds=2.40, probability=0.45, max_stake_pct=1.0)
        frac_stake = frac.calculate_stake(bankroll=1000, odds=2.40, probability=0.45, max_stake_pct=1.0)
        assert frac_stake == pytest.approx(full_stake * 0.25, abs=0.01)

    def test_respects_max(self):
        frac = FractionalKellyStrategy(fraction=0.25)
        stake = frac.calculate_stake(bankroll=1000, odds=2.40, probability=0.45, max_stake_pct=0.01)
        assert stake <= 10.0


class TestFlatStrategy:
    def test_default_2pct(self):
        strategy = FlatStrategy()
        stake = strategy.calculate_stake(bankroll=1000, odds=2.40, probability=0.45)
        assert stake == 20.0

    def test_custom_pct(self):
        strategy = FlatStrategy(flat_pct=0.05)
        stake = strategy.calculate_stake(bankroll=1000, odds=2.40, probability=0.45)
        assert stake == 50.0

    def test_max_cap(self):
        strategy = FlatStrategy(flat_pct=0.10)
        stake = strategy.calculate_stake(bankroll=1000, odds=2.40, probability=0.45, max_stake_pct=0.05)
        assert stake == 50.0  # capped at 5%


class TestFactory:
    def test_get_kelly(self):
        s = get_strategy("kelly")
        assert isinstance(s, KellyStrategy)

    def test_get_fractional_kelly(self):
        s = get_strategy("fractional_kelly", fraction=0.25)
        assert isinstance(s, FractionalKellyStrategy)

    def test_get_flat(self):
        s = get_strategy("flat", flat_pct=0.03)
        assert isinstance(s, FlatStrategy)

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            get_strategy("unknown")
