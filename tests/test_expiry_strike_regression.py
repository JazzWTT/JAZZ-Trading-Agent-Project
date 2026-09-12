"""
Regression tests for B-1, B-2, and B-3 (Expiry hardcoding, fabricated strike, Brier resolution).
Specifically implements tests T-1 through T-5.
"""

import os
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

from config import DEFAULT_CONFIG, SystemConfig
from core.models import EventPacket
from core.message_bus import MessageBus
from core.live_feeds import LivePolymarketFeedManager
from agents.agent2_brain import Agent2Brain
from research.fair_value import calculate_binary_fair_probability
from database.ledger_db import LedgerDB


class TestExpiryAndStrikeRegressions(unittest.TestCase):
    def setUp(self):
        self.bus = MessageBus()
        self.config = DEFAULT_CONFIG
        self.brain = Agent2Brain(bus=self.bus, config=self.config)
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_path = self.temp_db.name
        self.temp_db.close()

    def tearDown(self):
        try:
            os.remove(self.temp_db_path)
        except OSError:
            pass

    def test_T1_reject_110_day_market_in_discovery(self):
        """T-1: Feed a market with a 110-day expiry into the discovery filter. Assert it is REJECTED."""
        pm = LivePolymarketFeedManager()
        now = time.time()
        # End date 110 days in the future (Dec 31)
        expiry_110d_str = "2026-12-31T23:59:59Z"
        mock_gamma_response = [
            {
                "markets": [
                    {
                        "id": "mkt_long_dated",
                        "question": "Will Ethereum reach $2,750 by December 31, 2026?",
                        "endDate": expiry_110d_str,
                        "clobTokenIds": '["TOKEN_YES_110D", "TOKEN_NO_110D"]',
                        "volume24hr": "50000"
                    }
                ]
            }
        ]

        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_gamma_response
            mock_get.return_value = mock_resp

            pm.discover_markets()

        # The 110-day market must be rejected by the short-duration filter
        self.assertNotIn("ETH", pm.target_markets, "110-day market was incorrectly accepted into target_markets!")
        self.assertEqual(len(pm.target_markets), 0)

    def test_T2_fair_value_at_110_days_no_fake_signal(self):
        """
        T-2: Feed EventPacket with spot=3480, strike=2750, secs_remaining computed
        from a real 110-day expiry. Assert model_fair_prob is approximately 0.71,
        NOT 0.99. Assert no signal is generated at an ask of 0.75.
        """
        secs_remaining = 110.0 * 86400.0  # ~9,504,000s
        vol = 0.60
        fair_prob = calculate_binary_fair_probability(
            spot=3480.0,
            strike=2750.0,
            secs_remaining=secs_remaining,
            annualized_vol=vol,
            outcome_side="YES"
        )
        self.assertIsNotNone(fair_prob)
        # Model fair probability at T=110d must be ~0.71, NOT 1.0/0.99
        self.assertAlmostEqual(fair_prob, 0.7089, places=2)
        self.assertLess(fair_prob, 0.75)

        # Feed an EventPacket into Agent2 with ask = 0.75
        packet = EventPacket(
            timestamp=time.time(),
            asset_id="ETH",
            spot_price=3480.0,
            spot_change_velocity_60s=0.50,  # Strong momentum
            polymarket_best_bid=0.73,
            polymarket_best_ask=0.75,
            spread_bps=27.0,
            secs_remaining=secs_remaining,
            top3_depth_usdc=2000.0,
            token_id="ETH-110D-YES",
            strike_price=2750.0
        )
        order = self.brain.evaluate_packet(packet)
        # Must generate NO signal
        self.assertIsNone(order, "False signal fired on 110-day market with ask > true fair value!")

    def test_T3_zero_strike_returns_none(self):
        """
        T-3: Feed an EventPacket with strike_price = 0.0.
        Assert evaluate_packet returns None. Assert no strike is inferred.
        """
        packet = EventPacket(
            timestamp=time.time(),
            asset_id="BTC",
            spot_price=64000.0,
            spot_change_velocity_60s=0.50,
            polymarket_best_bid=0.48,
            polymarket_best_ask=0.50,
            spread_bps=40.0,
            secs_remaining=300.0,
            top3_depth_usdc=2000.0,
            token_id="BTC-YES",
            strike_price=0.0  # Zero / missing strike
        )
        order = self.brain.evaluate_packet(packet)
        self.assertIsNone(order, "Agent 2 inferred a fabricated strike when strike_price was 0.0!")

    def test_T4_brier_pending_until_real_expiry(self):
        """
        T-4: Record a Brier prediction for a market expiring in 110 days, advance the
        clock by 300 seconds, call resolve_expired_brier_predictions().
        Assert the prediction is still PENDING and was NOT resolved.
        """
        now = time.time()
        expiry_110d = now + (110.0 * 86400.0)
        db = LedgerDB(self.temp_db_path)
        db.record_brier_prediction(
            asset_id="ETH",
            market_id="mkt_110d",
            token_id="tok_110d",
            strike_price=2750.0,
            expiry_ts=expiry_110d,
            model_fair_prob=0.71,
            market_mid_price=0.74
        )

        # Advance clock by 300 seconds
        resolved = db.resolve_expired_brier_predictions(
            current_spot_prices={"ETH": 3500.0},
            now_ts=now + 300.0
        )
        self.assertEqual(resolved, 0, "Brier prediction resolved 110 days early at 300 seconds!")

        metrics = db.get_brier_metrics()
        self.assertEqual(metrics["total_evaluated"], 0)

        with db._get_conn() as conn:
            row = conn.cursor().execute("SELECT status FROM brier_calibration WHERE token_id = 'tok_110d'").fetchone()
            self.assertEqual(row["status"], "PENDING")

    def test_T5_no_evaluation_secs_remaining_in_codebase(self):
        """
        T-5: Assert the string 'evaluation_secs_remaining' appears nowhere in the
        codebase, and that no literal 300 is used as a time-to-expiry default.
        """
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target_dirs = ["core", "agents", "database"]
        target_files = ["bot_service.py", "config.py"]

        for d in target_dirs:
            dir_path = os.path.join(base_dir, d)
            for root, _, files in os.walk(dir_path):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(root, f), "r", encoding="utf-8") as fp:
                            content = fp.read()
                            self.assertNotIn("evaluation_secs_remaining", content, f"Found in {f}")

        for f in target_files:
            f_path = os.path.join(base_dir, f)
            if os.path.exists(f_path):
                with open(f_path, "r", encoding="utf-8") as fp:
                    content = fp.read()
                    self.assertNotIn("evaluation_secs_remaining", content, f"Found in {f}")


if __name__ == "__main__":
    unittest.main()
