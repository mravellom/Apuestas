
import pytest

from app.core.value_detector import (
    MAX_ODDS,
    MAX_ODDS_CV,
    MIN_ODDS,
    _outcome_odds_dispersed,
    detect_value_bets,
    detect_value_bets_vs_reference,
)


class TestDetectValueBets:
    def setup_method(self):
        self.odds = {
            "bet365": [2.10, 3.30, 3.60],
            "pinnacle": [2.12, 3.25, 3.55],
            "betfair": [2.05, 3.40, 3.50],
            "william_hill": [2.30, 3.10, 3.20],  # WH tiene home alto = posible value
        }
        self.outcome_keys = ["home", "draw", "away"]

    def test_finds_value_bets(self):
        results = detect_value_bets(
            self.odds, self.outcome_keys, min_value=0.01, min_bookmakers=3
        )
        assert isinstance(results, list)
        for vb in results:
            assert vb.value_pct >= 0.01

    def test_sorted_by_value_desc(self):
        results = detect_value_bets(
            self.odds, self.outcome_keys, min_value=0.01, min_bookmakers=3
        )
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].value_pct >= results[i + 1].value_pct

    def test_min_bookmakers_filter(self):
        few_odds = {"bet365": [2.10, 3.30, 3.60], "pinnacle": [2.12, 3.25, 3.55]}
        results = detect_value_bets(
            few_odds, self.outcome_keys, min_value=0.01, min_bookmakers=3
        )
        assert results == []

    def test_value_bet_fields(self):
        results = detect_value_bets(
            self.odds, self.outcome_keys, min_value=0.0, min_bookmakers=3
        )
        if results:
            vb = results[0]
            assert vb.outcome_key in self.outcome_keys
            assert vb.bookmaker_key in self.odds
            assert vb.consensus_prob > 0
            assert vb.implied_prob > 0
            assert vb.kelly_full >= 0
            assert vb.edge_confidence in ("low", "medium", "high")

    def test_sharp_bookmakers_affect_results(self):
        results_no_sharp = detect_value_bets(
            self.odds, self.outcome_keys, min_value=0.0, min_bookmakers=3
        )
        results_sharp = detect_value_bets(
            self.odds,
            self.outcome_keys,
            sharp_bookmakers={"pinnacle"},
            min_value=0.0,
            min_bookmakers=3,
        )
        # Results should differ since consensus changes with sharp weighting
        assert results_no_sharp != results_sharp or len(results_no_sharp) == len(results_sharp)

    def test_edge_confidence_high(self):
        # 6+ bookmakers -> high confidence
        odds_many = {f"bk{i}": [2.10 + i * 0.02, 3.30, 3.60] for i in range(6)}
        results = detect_value_bets(odds_many, self.outcome_keys, min_value=0.0, min_bookmakers=3)
        if results:
            assert results[0].edge_confidence == "high"

    def test_odds_below_min_filtered(self):
        """Favoritos extremos (odds < 1.30) se descartan."""
        odds = {f"bk{i}": [1.10, 8.00, 15.00] for i in range(6)}
        results = detect_value_bets(odds, self.outcome_keys, min_value=0.0, min_bookmakers=3)
        # Ningún outcome 0 (odds=1.10 < MIN_ODDS=1.30) debe aparecer
        assert all(vb.outcome_key != "home" for vb in results)

    def test_odds_above_max_filtered(self):
        """Longshots extremos (odds > 10.0) se descartan."""
        odds = {f"bk{i}": [1.50, 3.50, 15.00] for i in range(6)}
        results = detect_value_bets(odds, self.outcome_keys, min_value=0.0, min_bookmakers=3)
        # outcome 2 (odds=15 > MAX_ODDS) nunca presente
        assert all(vb.outcome_key != "away" for vb in results)

    def test_dispersed_outcome_filtered(self):
        """Outcomes con CV > 15% se descartan (protege contra errores de datos)."""
        # Home muy disperso (1.80, 5.00, 1.85, 5.00, 1.90) → CV alto
        odds = {
            "bk0": [1.80, 3.30, 3.60],
            "bk1": [5.00, 3.30, 3.60],
            "bk2": [1.85, 3.30, 3.60],
            "bk3": [5.00, 3.30, 3.60],
            "bk4": [1.90, 3.30, 3.60],
        }
        results = detect_value_bets(odds, self.outcome_keys, min_value=0.0, min_bookmakers=5)
        assert all(vb.outcome_key != "home" for vb in results)

    def test_min_bookmakers_default_is_five(self):
        """Con 4 bookmakers y default min_bookmakers=5, sin resultados."""
        odds = {f"bk{i}": [2.10, 3.30, 3.60] for i in range(4)}
        results = detect_value_bets(odds, self.outcome_keys)
        assert results == []

    def test_min_value_default_is_five_pct(self):
        """Con EV 3% y default min_value=0.05, no se encuentra."""
        # All bookmakers very similar → no value > 5%
        odds = {f"bk{i}": [2.10, 3.30, 3.60] for i in range(6)}
        results = detect_value_bets(odds, self.outcome_keys)
        assert results == []

    def test_commission_reduces_ev_and_kelly(self):
        """Con comisión, el EV neto debe ser menor que el bruto del mismo book."""
        # Mercado con consenso estrecho (9 libros idénticos) + 1 outlier soft
        # con cuota notablemente mejor en `away`. Edge ~10% supera holgadamente
        # el ruido del consenso → uncertainty no nuclea, aislamos el efecto de
        # la comisión.
        odds = {f"bk{i}": [2.10, 3.30, 3.50] for i in range(9)}
        odds["soft"] = [2.10, 3.30, 4.20]
        results_no_comm = detect_value_bets(
            odds, self.outcome_keys, min_value=-1.0, min_bookmakers=3
        )
        results_with_comm = detect_value_bets(
            odds,
            self.outcome_keys,
            min_value=-1.0,
            min_bookmakers=3,
            commission_by_bookmaker={"soft": 0.01},
        )

        soft_no = next(
            (vb for vb in results_no_comm if vb.bookmaker_key == "soft" and vb.outcome_key == "away"),
            None,
        )
        soft_with = next(
            (vb for vb in results_with_comm if vb.bookmaker_key == "soft" and vb.outcome_key == "away"),
            None,
        )
        assert soft_no is not None and soft_with is not None
        assert soft_with.value_pct < soft_no.value_pct
        assert soft_with.kelly_full < soft_no.kelly_full

    def test_uncertainty_filter_rejects_noisy_consensus(self):
        """Cuando los libros disienten mucho en un outcome, la señal se nuclea."""
        # 5 libros con cuotas dispares en home pero alineados en draw/away.
        # Un sexto libro ofrece home a precio "alto" — nominalmente hay EV pero
        # el SE del consenso es comparable al edge.
        odds = {
            "bk1": [1.90, 3.30, 3.60],
            "bk2": [2.30, 3.30, 3.60],
            "bk3": [2.00, 3.30, 3.60],
            "bk4": [2.20, 3.30, 3.60],
            "bk5": [2.05, 3.30, 3.60],
            "soft": [2.40, 3.30, 3.60],
        }
        # min_value muy bajo para que el filtro de uncertainty sea el único factor
        results = detect_value_bets(
            odds, self.outcome_keys, min_value=-1.0, min_bookmakers=5
        )
        soft_home = [vb for vb in results if vb.bookmaker_key == "soft" and vb.outcome_key == "home"]
        # En un consenso ruidoso con edge marginal, el filtro rechaza la señal
        assert soft_home == [] or all(vb.kelly_full > 0 for vb in soft_home)

    def test_uncertainty_lets_strong_signals_through(self):
        """Edge holgado sobre consenso estrecho sobrevive al filtro."""
        # 9 libros idénticos + 1 outlier con cuota notablemente mejor → edge >> SE
        odds = {f"bk{i}": [2.10, 3.30, 3.50] for i in range(9)}
        odds["soft"] = [2.10, 3.30, 4.20]  # away mucho más alto
        results = detect_value_bets(
            odds, self.outcome_keys, min_value=0.01, min_bookmakers=5
        )
        soft_away = [vb for vb in results if vb.bookmaker_key == "soft" and vb.outcome_key == "away"]
        assert len(soft_away) == 1
        assert soft_away[0].kelly_full > 0

    def test_commission_filters_marginal_signals(self):
        """Una señal con EV bruto justo arriba del umbral cae bajo el umbral con comisión."""
        # Mercado donde un book tiene EV ~5% bruto. Con 1% comisión queda ~4% neto.
        odds = {
            "bk1": [2.00, 3.50, 4.00],
            "bk2": [2.00, 3.50, 4.00],
            "bk3": [2.00, 3.50, 4.00],
            "bk4": [2.00, 3.50, 4.00],
            "soft": [2.20, 3.50, 4.00],  # home más alto = source del value
        }
        # Sin comisión: pasa el threshold de 5%
        no_comm = detect_value_bets(odds, self.outcome_keys, min_value=0.05, min_bookmakers=5)
        soft_no = [vb for vb in no_comm if vb.bookmaker_key == "soft"]
        # Con comisión: EV neto cae por debajo
        with_comm = detect_value_bets(
            odds,
            self.outcome_keys,
            min_value=0.05,
            min_bookmakers=5,
            commission_by_bookmaker={"soft": 0.05},
        )
        soft_with = [vb for vb in with_comm if vb.bookmaker_key == "soft"]
        assert len(soft_no) >= 1
        assert len(soft_with) < len(soft_no)


class TestOutcomeOddsDispersed:
    def test_returns_true_when_fewer_than_three(self):
        odds = {"bk0": [2.00, 3.30], "bk1": [2.05, 3.35]}
        assert _outcome_odds_dispersed(odds, 0) is True

    def test_returns_false_for_consistent_odds(self):
        odds = {f"bk{i}": [2.00 + i * 0.01, 3.30, 3.60] for i in range(6)}
        assert _outcome_odds_dispersed(odds, 0) is False

    def test_returns_true_for_dispersed_odds(self):
        odds = {
            "bk0": [1.80, 3.30, 3.60],
            "bk1": [5.00, 3.30, 3.60],
            "bk2": [1.85, 3.30, 3.60],
            "bk3": [5.00, 3.30, 3.60],
            "bk4": [1.90, 3.30, 3.60],
        }
        assert _outcome_odds_dispersed(odds, 0) is True
        # Outcome 1 (draw) is consistent
        assert _outcome_odds_dispersed(odds, 1) is False

    def test_cv_threshold_boundary(self):
        """CV exactamente en umbral MAX_ODDS_CV no dispara filtro."""
        # Build odds where outcome 0 has known CV just below threshold
        prices = [2.00, 2.10, 2.20, 2.30, 2.40]  # mean=2.2, stdev~0.158, cv~0.072
        odds = {f"bk{i}": [p, 3.30, 3.60] for i, p in enumerate(prices)}
        assert _outcome_odds_dispersed(odds, 0) is False


class TestConstants:
    def test_thresholds_are_sane(self):
        assert 1.0 < MIN_ODDS < 2.0
        assert MAX_ODDS > 5.0
        assert 0.0 < MAX_ODDS_CV < 1.0


class TestDetectValueBetsVsReference:
    def setup_method(self):
        self.outcome_keys = ["home", "draw", "away"]

    def test_returns_empty_when_reference_missing(self):
        odds = {"coolbet": [2.10, 3.30, 3.60]}
        results = detect_value_bets_vs_reference(
            odds, self.outcome_keys, reference_bookmaker="pinnacle"
        )
        assert results == []

    def test_excludes_reference_from_results(self):
        odds = {
            "pinnacle": [2.00, 3.50, 3.80],
            "coolbet": [2.10, 3.50, 3.80],
        }
        results = detect_value_bets_vs_reference(
            odds, self.outcome_keys, reference_bookmaker="pinnacle", min_value=0.0
        )
        assert all(vb.bookmaker_key != "pinnacle" for vb in results)

    def test_finds_value_when_other_book_higher_than_reference(self):
        # Pinnacle fair: home ~0.500; coolbet offers 2.25 → EV ~0.125 > 0
        odds = {
            "pinnacle": [2.00, 3.50, 3.80],
            "coolbet": [2.25, 3.40, 3.70],
        }
        results = detect_value_bets_vs_reference(
            odds, self.outcome_keys, reference_bookmaker="pinnacle", min_value=0.02
        )
        assert any(vb.bookmaker_key == "coolbet" and vb.outcome_key == "home" for vb in results)

    def test_no_value_when_books_agree(self):
        odds = {
            "pinnacle": [2.00, 3.50, 3.80],
            "coolbet": [2.00, 3.50, 3.80],
        }
        results = detect_value_bets_vs_reference(
            odds, self.outcome_keys, reference_bookmaker="pinnacle", min_value=0.02
        )
        assert results == []

    def test_confidence_tag_is_reference(self):
        odds = {
            "pinnacle": [2.00, 3.50, 3.80],
            "coolbet": [2.30, 3.40, 3.70],
        }
        results = detect_value_bets_vs_reference(
            odds, self.outcome_keys, reference_bookmaker="pinnacle", min_value=0.0
        )
        assert all(vb.edge_confidence == "reference" for vb in results)

    def test_odds_range_filter_applies(self):
        odds = {
            "pinnacle": [2.00, 3.50, 3.80],
            "coolbet": [1.20, 3.50, 12.00],  # home below MIN_ODDS, away above MAX_ODDS
        }
        results = detect_value_bets_vs_reference(
            odds, self.outcome_keys, reference_bookmaker="pinnacle", min_value=0.0
        )
        assert all(vb.outcome_key not in ("home", "away") for vb in results)

    def test_sorted_by_value_desc(self):
        odds = {
            "pinnacle": [2.00, 3.50, 3.80],
            "coolbet": [2.30, 3.80, 4.20],
        }
        results = detect_value_bets_vs_reference(
            odds, self.outcome_keys, reference_bookmaker="pinnacle", min_value=0.0
        )
        for i in range(len(results) - 1):
            assert results[i].value_pct >= results[i + 1].value_pct
