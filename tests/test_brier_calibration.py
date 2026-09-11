"""
Unit tests for Brier Score Calibration Tournament.
Tests mathematical edge verification in research/fair_value.py and
database persistence/resolution in database/ledger_db.py.
"""

import os
import tempfile
import time
import unittest

from database.ledger_db import LedgerDB
from research.fair_value import compute_brier_score, evaluate_brier_skill


class TestBrierScoreMath(unittest.TestCase):
    def test_empty_predictions(self):
        self.assertEqual(compute_brier_score([], []), 0.0)

    def test_perfect_predictions(self):
        # Model predicted exactly right
        preds = [1.0, 0.0, 1.0]
        outcomes = [1, 0, 1]
        score = compute_brier_score(preds, outcomes)
        self.assertEqual(score, 0.0)

    def test_worst_possible_predictions(self):
        # Model predicted completely wrong
        preds = [0.0, 1.0]
        outcomes = [1, 0]
        score = compute_brier_score(preds, outcomes)
        self.assertEqual(score, 1.0)

    def test_uninformative_prior(self):
        # Guessing 50/50 on binary events yields Brier = 0.25
        preds = [0.5, 0.5, 0.5, 0.5]
        outcomes = [1, 0, 1, 0]
        score = compute_brier_score(preds, outcomes)
        self.assertAlmostEqual(score, 0.25, places=5)

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            compute_brier_score([0.5, 0.6], [1])

    def test_evaluate_brier_skill(self):
        # Model is closer to truth than market
        model_probs = [0.8, 0.2]
        market_mids = [0.5, 0.5]
        outcomes = [1, 0]

        res = evaluate_brier_skill(model_probs, market_mids, outcomes)
        self.assertLess(res["brier_model"], res["brier_market"])
        self.assertGreater(res["skill_delta"], 0.0)
        self.assertTrue(res["model_beats_market"])

        # Market is closer to truth than model
        mkt_probs = [0.9, 0.1]
        bad_model = [0.4, 0.6]
        res2 = evaluate_brier_skill(bad_model, mkt_probs, outcomes)
        self.assertGreater(res2["brier_model"], res2["brier_market"])
        self.assertLess(res2["skill_delta"], 0.0)
        self.assertFalse(res2["model_beats_market"])


class TestBrierDatabaseLedger(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()
        self.db = LedgerDB(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def test_record_and_resolve_brier_prediction(self):
        now = time.time()
        expiry = now - 10.0  # Already expired

        # 1. Record prediction
        self.db.record_brier_prediction(
            asset_id="BTC",
            market_id="btc_test_market_1",
            token_id="token_btc_yes_1",
            strike_price=80000.0,
            expiry_ts=expiry,
            model_fair_prob=0.75,
            market_mid_price=0.60
        )

        # Verify initial pending state in metrics
        metrics_pending = self.db.get_brier_metrics()
        self.assertEqual(metrics_pending["total_evaluated"], 0)

        # 2. Resolve expired predictions with terminal spot >= strike (outcome = 1)
        spot_prices = {"BTC": 80500.0}
        resolved = self.db.resolve_expired_brier_predictions(spot_prices, now_ts=now)
        self.assertEqual(resolved, 1)

        # 3. Check resolved metrics
        metrics_resolved = self.db.get_brier_metrics()
        self.assertEqual(metrics_resolved["total_evaluated"], 1)

        # Model: (0.75 - 1.0)^2 = 0.0625
        # Market: (0.60 - 1.0)^2 = 0.1600
        # Skill delta: 0.1600 - 0.0625 = +0.0975
        self.assertAlmostEqual(metrics_resolved["brier_model"], 0.0625, places=4)
        self.assertAlmostEqual(metrics_resolved["brier_market"], 0.1600, places=4)
        self.assertAlmostEqual(metrics_resolved["skill_delta"], 0.0975, places=4)

        # Verify recent evaluations list
        recent = metrics_resolved["recent_evaluations"]
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["actual_outcome"], 1)
        self.assertEqual(recent[0]["asset_id"], "BTC")

    def test_unexpired_not_resolved(self):
        now = time.time()
        future_expiry = now + 500.0  # Not expired yet

        self.db.record_brier_prediction(
            asset_id="ETH",
            market_id="eth_test_market_1",
            token_id="token_eth_yes_1",
            strike_price=2500.0,
            expiry_ts=future_expiry,
            model_fair_prob=0.80,
            market_mid_price=0.50
        )

        resolved = self.db.resolve_expired_brier_predictions({"ETH": 2600.0}, now_ts=now)
        self.assertEqual(resolved, 0)
        metrics = self.db.get_brier_metrics()
        self.assertEqual(metrics["total_evaluated"], 0)

    def test_statistical_edge_threshold(self):
        # If N >= 10 and skill_delta > 0, has_statistical_edge must be True
        now = time.time()
        for i in range(12):
            self.db.record_brier_prediction(
                asset_id="SOL",
                market_id=f"sol_market_{i}",
                token_id=f"sol_token_{i}",
                strike_price=150.0,
                expiry_ts=now - 5.0,
                model_fair_prob=0.90,
                market_mid_price=0.50
            )

        self.db.resolve_expired_brier_predictions({"SOL": 160.0}, now_ts=now)
        metrics = self.db.get_brier_metrics()
        self.assertEqual(metrics["total_evaluated"], 12)
        self.assertGreater(metrics["skill_delta"], 0.0)
        self.assertTrue(metrics["has_statistical_edge"])


if __name__ == "__main__":
    unittest.main()
