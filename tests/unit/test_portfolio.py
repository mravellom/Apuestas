"""Tests del portfolio allocator."""

from app.core.portfolio import PortfolioBet, allocate_portfolio


def _bet(bet_id: str, match_id: int, kelly: float) -> PortfolioBet:
    return PortfolioBet(bet_id=bet_id, match_id=match_id, raw_kelly=kelly)


class TestAllocatePortfolio:
    def test_empty_input(self):
        result = allocate_portfolio([], available_exposure=0.20)
        assert result == []

    def test_no_exposure_left_skips_all(self):
        bets = [_bet("a", 1, 0.10), _bet("b", 2, 0.08)]
        result = allocate_portfolio(bets, available_exposure=0.0)
        assert all(r.skipped and r.stake == 0.0 for r in result)
        assert all(r.reason == "exposure_full" for r in result)

    def test_within_budget_uses_fractional_and_cap(self):
        # raw_kelly 0.10 → 0.025 con 1/4. Bajo el cap 0.05.
        bets = [_bet("a", 1, 0.10), _bet("b", 2, 0.08)]
        result = allocate_portfolio(bets, available_exposure=0.20)
        a = next(r for r in result if r.bet_id == "a")
        b = next(r for r in result if r.bet_id == "b")
        assert a.stake == 0.10 * 0.25
        assert b.stake == 0.08 * 0.25
        assert not a.skipped and not b.skipped

    def test_per_bet_cap_applied(self):
        # raw_kelly 0.40 × 0.25 = 0.10 → capeado a 0.05
        bets = [_bet("a", 1, 0.40)]
        result = allocate_portfolio(bets, available_exposure=0.20)
        assert result[0].stake == 0.05

    def test_correlated_legs_only_best_survives(self):
        # Dos legs del mismo match: solo la mayor Kelly entra al portfolio.
        bets = [_bet("a", 1, 0.04), _bet("b", 1, 0.10), _bet("c", 2, 0.05)]
        result = allocate_portfolio(bets, available_exposure=0.20)
        a = next(r for r in result if r.bet_id == "a")
        b = next(r for r in result if r.bet_id == "b")
        c = next(r for r in result if r.bet_id == "c")
        assert a.skipped and a.reason == "correlated_leg_dropped"
        assert not b.skipped
        assert not c.skipped

    def test_proportional_scaling_when_over_budget(self):
        # Tres bets cada una pidiendo 0.05 → suma 0.15. Budget 0.06 → factor 0.4.
        bets = [_bet("a", 1, 0.20), _bet("b", 2, 0.20), _bet("c", 3, 0.20)]
        # raw_kelly 0.20 × 0.25 = 0.05 cada una; 3 × 0.05 = 0.15 desired
        result = allocate_portfolio(bets, available_exposure=0.06)
        stakes = {r.bet_id: r.stake for r in result}
        assert abs(sum(stakes.values()) - 0.06) < 1e-9
        # Proporcionales: cada uno 0.06/3 = 0.02
        for s in stakes.values():
            assert abs(s - 0.02) < 1e-9

    def test_zero_kelly_excluded(self):
        bets = [_bet("a", 1, 0.0), _bet("b", 2, 0.08)]
        result = allocate_portfolio(bets, available_exposure=0.20)
        a = next(r for r in result if r.bet_id == "a")
        b = next(r for r in result if r.bet_id == "b")
        assert a.skipped and a.reason == "zero_kelly"
        assert not b.skipped

    def test_preserves_input_order(self):
        bets = [_bet("z", 3, 0.05), _bet("a", 1, 0.06), _bet("m", 2, 0.04)]
        result = allocate_portfolio(bets, available_exposure=0.20)
        assert [r.bet_id for r in result] == ["z", "a", "m"]
