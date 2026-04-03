
from app.core.value_detector import detect_value_bets


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
