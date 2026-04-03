from app.core.formulas import kelly_criterion
from app.core.staking.base import StakingStrategy


class KellyStrategy(StakingStrategy):
    def calculate_stake(
        self,
        bankroll: float,
        odds: float,
        probability: float,
        max_stake_pct: float = 0.05,
    ) -> float:
        kelly_pct = kelly_criterion(probability, odds)
        pct = min(kelly_pct, max_stake_pct)
        return round(bankroll * pct, 2)


class FractionalKellyStrategy(StakingStrategy):
    def __init__(self, fraction: float = 0.25):
        self.fraction = fraction

    def calculate_stake(
        self,
        bankroll: float,
        odds: float,
        probability: float,
        max_stake_pct: float = 0.05,
    ) -> float:
        kelly_pct = kelly_criterion(probability, odds)
        pct = min(kelly_pct * self.fraction, max_stake_pct)
        return round(bankroll * pct, 2)
