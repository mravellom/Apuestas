from abc import ABC, abstractmethod


class StakingStrategy(ABC):
    @abstractmethod
    def calculate_stake(
        self,
        bankroll: float,
        odds: float,
        probability: float,
        max_stake_pct: float = 0.05,
    ) -> float:
        """Retorna el monto a apostar."""
        ...
