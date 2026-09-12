"""
Unit and regression tests for Brier Tournament Passive Mode,
Pre-Burst Volatility Isolation, and Hourly Market Per-Tick Eligibility.
"""

import asyncio
import os
import random
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

from config import DEFAULT_CONFIG, SystemConfig
from core.models import EventPacket, DecisionOrder
from core.message_bus import MessageBus
from core.live_feeds import LivePolymarketFeedManager
from agents.agent1_eyes import Agent1Eyes
from agents.agent2_brain import Agent2Brain
from agents.agent3_hands import Agent3Hands
from agents.agent4_shield import Agent4Shield
from database.ledger_db import LedgerDB
from research.fair_value import (
    calculate_baseline_volatility,
    calculate_realized_volatility_60s,
    calculate_binary_fair_probability
)


class TestBrierPassiveTournament(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_path = self.temp_db.name
        self.temp_db.close()
        self.db = LedgerDB(self.temp_db_path)
        self.bus = MessageBus()

    def tearDown(self):
        try:
            os.remove(self.temp_db_path)
        except OSError:
            pass

    def test_baseline_volatility_excludes_momentum_burst(self):
        """
        Verify that calculate_baseline_volatility measures ONLY the pre-burst window [now-360s, now-60s]
        and is mathematically identical regardless of whatever erratic price shock happens in trailing 60s.
        """
        now = 10000.0
        base_price = 70000.0

        # Construct pre-burst baseline from t=9600 to t=9940 (340 seconds, [now-400, now-60])
        history_calm = [(9600.0 + i, base_price + (i % 5)) for i in range(341)]
        history_burst = list(history_calm)

        # In trailing 60s for history_calm: perfectly flat price
        for i in range(1, 60):
            history_calm.append((9940.0 + i, base_price))

        # In trailing 60s for history_burst: violent momentum shock with huge swings
        burst_prices = []
        for i in range(1, 60):
            p = base_price + (i * 20.0) + (150.0 if i % 2 == 0 else -150.0)
            history_burst.append((9940.0 + i, p))
            burst_prices.append(p)

        # Baseline vol on calm history vs burst history
        vol_calm = calculate_baseline_volatility(
            price_history=history_calm,
            now_ts=now,
            burst_window_sec=60.0,
            baseline_window_sec=300.0
        )
        vol_burst = calculate_baseline_volatility(
            price_history=history_burst,
            now_ts=now,
            burst_window_sec=60.0,
            baseline_window_sec=300.0
        )

        # 1. Baseline volatility must be IDENTICAL (trailing 60s shock is 100% excluded)
        self.assertAlmostEqual(vol_calm, vol_burst, places=7)

        # 2. Baseline volatility is realistic calm volatility
        self.assertGreater(vol_calm, 0.05)
        self.assertLess(vol_calm, 0.35)

        # 3. Trailing 60s volatility is contaminated by the burst
        burst_vol = calculate_realized_volatility_60s(burst_prices)
        self.assertIsNotNone(burst_vol)
        self.assertGreater(burst_vol, 5.0)  # Violent burst has massive variance

    def test_agent1_baseline_volatility_integration(self):
        """Verify Agent1Eyes calculates and populates baseline volatility into EventPacket."""
        eyes = Agent1Eyes(bus=self.bus)
        now = time.time()

        # Seed 360s of calm prices for BTC (0 to 4 point fluctuations)
        for s in range(360):
            eyes.update_spot_price("BTC", 80000.0 + (s % 5), ts=now - 360.0 + s)

        # Inject trailing 60s momentum spike (+150 point jump)
        for s in range(60):
            eyes.update_spot_price("BTC", 80000.0 + (s * 5.0) + (50.0 if s % 2 == 0 else -50.0), ts=now - 60.0 + s)

        packet = eyes.update_polymarket_clob(
            asset="BTC",
            bids=[(0.50, 1000)],
            asks=[(0.52, 1000)],
            secs_remaining=300,
            token_id="BTC-HOURLY-YES",
            strike_price=80000.0,
            ts=now
        )

        self.assertIsNotNone(packet)
        self.assertIsNotNone(packet.realized_vol_60s)
        # Realized vol in packet must be baseline vol (~0.16), not contaminated by the spike
        self.assertLess(packet.realized_vol_60s, 0.30)
        self.assertGreater(packet.realized_vol_60s, 0.05)

    def test_hourly_market_discovery_and_per_tick_eligibility(self):
        """
        Verify that discover_markets() accepts hourly contracts (e.g. maturing in 45 mins),
        rejects long-dated 110-day contracts, and computes eligibility per tick.
        """
        pm = LivePolymarketFeedManager()
        now = time.time()

        # Mock Gamma API response with:
        # 1. BTC hourly contract expiring in 45 mins (2700s)
        # 2. ETH long-dated contract expiring in 110 days (~9.5M s)
        mock_events = [
            {
                "markets": [
                    {
                        "id": "mkt_btc_hourly",
                        "question": "Will Bitcoin reach $85,000 by 11:00 PM?",
                        "endDate": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 2700)),
                        "clobTokenIds": '["BTC_YES_TOK", "BTC_NO_TOK"]',
                        "volume24hr": "10000"
                    },
                    {
                        "id": "mkt_eth_110d",
                        "question": "Will Ethereum reach $3,000 by December 31, 2026?",
                        "endDate": "2026-12-31T23:59:59Z",
                        "clobTokenIds": '["ETH_YES_TOK", "ETH_NO_TOK"]',
                        "volume24hr": "50000"
                    }
                ]
            }
        ]

        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_events
            mock_get.return_value = mock_resp

            pm.discover_markets()

        # BTC hourly contract MUST be discovered
        self.assertIn("BTC", pm.target_markets)
        self.assertEqual(pm.target_markets["BTC"]["market_id"], "mkt_btc_hourly")
        self.assertEqual(pm.target_markets["BTC"]["strike_price"], 85000.0)

        # ETH 110-day contract MUST be rejected
        self.assertNotIn("ETH", pm.target_markets)

        # Test per-tick eligibility transitions
        expiry = now + 2700.0  # 45 minutes

        # At T=2700s: dormant (outside danger zone)
        self.assertFalse(pm.is_market_eligible(expiry, now_ts=now))

        # At T=600s: eligible (ceiling of danger zone)
        self.assertTrue(pm.is_market_eligible(expiry, now_ts=expiry - 600.0))

        # At T=300s: eligible (inside danger zone)
        self.assertTrue(pm.is_market_eligible(expiry, now_ts=expiry - 300.0))

        # At T=120s: eligible (floor of danger zone)
        self.assertTrue(pm.is_market_eligible(expiry, now_ts=expiry - 120.0))

        # At T=60s: ineligible (below danger zone floor of 120s)
        self.assertFalse(pm.is_market_eligible(expiry, now_ts=expiry - 60.0))

    async def test_passive_tournament_mode_suppresses_all_orders(self):
        """
        Verify that with passive_tournament_mode=True:
        1. Shield blocks all order forwarding to execution_commands.
        2. Hands rejects any execution attempt immediately.
        3. Zero trades/executions are posted to database.
        """
        config = SystemConfig(passive_tournament_mode=True, db_path=self.temp_db_path)
        shield = Agent4Shield(bus=self.bus, db=self.db, config=config)
        hands = Agent3Hands(bus=self.bus, db=self.db, config=config)

        await shield.start()
        await hands.start()

        approved_commands = []
        self.bus.subscribe("execution_commands", lambda o: approved_commands.append(o))

        order = DecisionOrder(
            signal_id="SIG-PASSIVE-01",
            action="BUY",
            token_id="BTC-HOURLY-YES",
            target_limit_price=0.50,
            calculated_edge_bps=500.0,
            max_size_shares=100.0
        )

        # 1. Shield evaluation must suppress order
        await shield.evaluate_signal_risk(order)
        self.assertEqual(len(approved_commands), 0, "Shield permitted order dispatch in passive tournament mode!")

        # 2. Hands direct execution must raise RuntimeError (permanently disabled)
        with self.assertRaises(RuntimeError) as ctx:
            await hands.execute_order(order)
        self.assertEqual(str(ctx.exception), "Strategy shelved. Execution permanently disabled.")

        # 3. Verify zero execution records in DB
        with self.db._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM executions")
            count = cur.fetchone()[0]
            self.assertEqual(count, 0, "Execution was written to database in passive tournament mode!")

        await shield.stop()
        await hands.stop()

    def test_passive_brier_calibration_flow(self):
        """
        Verify that in passive mode, model forecasts vs market mid quotes are
        recorded and resolved against terminal spot prices to evaluate S-2.
        """
        now = time.time()
        expiry = now + 300.0

        # Simulate recording an eligible prediction
        self.db.record_brier_prediction(
            asset_id="BTC",
            market_id="mkt_btc_calib",
            token_id="tok_btc_yes",
            strike_price=80000.0,
            expiry_ts=expiry,
            model_fair_prob=0.75,
            market_mid_price=0.60
        )

        # Before expiry: pending
        metrics_pre = self.db.get_brier_metrics()
        self.assertEqual(metrics_pre["total_evaluated"], 0)

        # At expiry: resolve with terminal spot = 81000 (> 80000 strike -> outcome = 1)
        resolved = self.db.resolve_expired_brier_predictions(
            current_spot_prices={"BTC": 81000.0},
            now_ts=expiry + 1.0
        )
        self.assertEqual(resolved, 1)

        metrics_post = self.db.get_brier_metrics()
        self.assertEqual(metrics_post["total_evaluated"], 1)
        self.assertAlmostEqual(metrics_post["brier_model"], 0.0625, places=4)
        self.assertAlmostEqual(metrics_post["brier_market"], 0.1600, places=4)
        self.assertGreater(metrics_post["skill_delta"], 0.0)


if __name__ == "__main__":
    unittest.main()