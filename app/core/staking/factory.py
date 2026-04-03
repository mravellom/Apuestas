from app.core.staking.base import StakingStrategy
from app.core.staking.flat import FlatStrategy
from app.core.staking.kelly import FractionalKellyStrategy, KellyStrategy

_STRATEGIES: dict[str, type[StakingStrategy]] = {
    "kelly": KellyStrategy,
    "fractional_kelly": FractionalKellyStrategy,
    "flat": FlatStrategy,
}


def get_strategy(name: str, **kwargs) -> StakingStrategy:
    """Factory para obtener una estrategia de staking por nombre."""
    strategy_cls = _STRATEGIES.get(name)
    if strategy_cls is None:
        raise ValueError(f"Unknown staking strategy: {name}. Options: {list(_STRATEGIES.keys())}")
    return strategy_cls(**kwargs)
