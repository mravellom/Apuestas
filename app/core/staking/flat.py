from app.core.staking.base import StakingStrategy


class FlatStrategy(StakingStrategy):
    def __init__(self, flat_pct: float = 0.02):
        self.flat_pct = flat_pct

    def calculate_stake(
        self,
        bankroll: float,
        odds: float,
        probability: float,
        max_stake_pct: float = 0.05,
    ) -> float:
        pct = min(self.flat_pct, max_stake_pct)
        return round(bankroll * pct, 2)
