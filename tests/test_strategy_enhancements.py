"""
Unit tests for Quantitative Strategy Enhancements
Tests Cross-Venue Consensus, Order Flow Imbalance (OFI), and Brain gate filtering.
"""

import time
import unittest
from collections import deque

from config import DEFAULT_CONFIG, SystemConfig, StrategyEnhancementConfig
from core.live_feeds import LiveSpotFeedManager, LivePolymarketFeedManager
from core.models import EventPacket
from core.message_bus import MessageBus
from agents.agent2_brain import Agent2Brain


class TestStrategyEnhancements(unittest.TestCase):
    def setUp(self):
        self.bus = MessageBus()
        self.config = DEFAULT_CONFIG
        self.brain = Agent2Brain(bus=self.bus, config=self.config)

    def test_cross_venue_consensus_validation(self):
        """Spot manager requires directional agreement between Coinbase and OKX."""
        mgr = LiveSpotFeedManager()
        now = time.time()
        
        # Populate Coinbase with upward momentum (+0.5%)
        mgr.coinbase_history["BTC"] = deque([
            (now - 60.0, 70000.0),
            (now - 30.0, 70150.0),
            (now, 70350.0)
        ], maxlen=300)
        
        # Populate OKX with upward momentum (+0.4%)
        mgr.okx_history["BTC"] = deque([
            (now - 60.0, 70000.0),
            (now - 30.0, 70100.0),
            (now, 70280.0)
        ], maxlen=300)

        # Both venues agree upward -> UP should pass
        self.assertTrue(mgr.check_cross_venue_consensus("BTC", "UP"))
        # DOWN should fail
        self.assertFalse(mgr.check_cross_venue_consensus("BTC", "DOWN"))

        # Now simulate divergent wick: OKX is selling off while Coinbase spikes
        mgr.okx_history["BTC"] = deque([
            (now - 60.0, 70200.0),
            (now - 30.0, 70000.0),
            (now, 69800.0)
        ], maxlen=300)
        # Coinbase up (+0.5%) but OKX down (-0.57%) -> UP should be rejected
        self.assertFalse(mgr.check_cross_venue_consensus("BTC", "UP"))

    def test_order_flow_imbalance_calculation(self):
        """CLOB manager accurately computes OFI = (bids - asks) / (bids + asks) on top 5 levels."""
        pm = LivePolymarketFeedManager()
        pm.target_markets = {
            "BTC": {
                "asset": "BTC",
                "market_id": "m1",
                "question": "Will BTC reach $100k?",
                "strike_price": 100000.0,
                "token_id_yes": "T_YES",
                "token_id_no": "T_NO",
                "expiry_ts": time.time() + 300.0
            }
        }
        pm.token_to_asset = {"T_YES": ("BTC", "YES")}

        # 1. Heavy Bid Support: bids 3000 shares, asks 1000 shares -> OFI = (3000 - 1000) / 4000 = +0.50
        snapshot_bids = {
            "event_type": "book",
            "asset_id": "T_YES",
            "bids": [{"price": "0.50", "size": "3000"}],
            "asks": [{"price": "0.52", "size": "1000"}]
        }
        pm._process_clob_item(snapshot_bids, now=time.time())
        book = pm.books["T_YES"]
        self.assertAlmostEqual(book["ofi"], 0.50, places=2)

        # 2. Heavy Ask Resistance: bids 500 shares, asks 2500 shares -> OFI = (500 - 2500) / 3000 = -0.6667
        snapshot_asks = {
            "event_type": "book",
            "asset_id": "T_YES",
            "bids": [{"price": "0.50", "size": "500"}],
            "asks": [{"price": "0.52", "size": "2500"}]
        }
        pm._process_clob_item(snapshot_asks, now=time.time())
        book = pm.books["T_YES"]
        self.assertAlmostEqual(book["ofi"], -0.6667, places=2)

    def test_brain_ofi_filter_suppresses_adverse_trades(self):
        """Agent2Brain suppresses signals when OFI opposes the trade direction."""
        # Explicitly enable OFI filter for this enhancement unit test
        self.brain.config.enhancements.ofi_filter_enabled = True

        packet_adverse_yes = EventPacket(
            timestamp=time.time(),
            asset_id="BTC",
            spot_price=70500.0,
            spot_change_velocity_60s=0.45,  # Strong upward momentum (+0.45% >= +0.30%)
            polymarket_best_bid=0.48,
            polymarket_best_ask=0.50,
            spread_bps=40.0,
            secs_remaining=300,
            top3_depth_usdc=2500.0,
            token_id="BTC-YES",
            strike_price=70000.0,
            ofi=-0.65,  # Adverse heavy selling pressure on YES token
            cross_venue_confirmed=True
        )
        # Should be suppressed by OFI filter
        order = self.brain.evaluate_packet(packet_adverse_yes)
        self.assertIsNone(order)

        # Now test with supportive OFI (+0.25 > -0.40)
        packet_supportive_yes = EventPacket(
            timestamp=time.time(),
            asset_id="BTC",
            spot_price=70500.0,
            spot_change_velocity_60s=0.45,
            polymarket_best_bid=0.48,
            polymarket_best_ask=0.50,
            spread_bps=40.0,
            secs_remaining=300,
            top3_depth_usdc=2500.0,
            token_id="BTC-YES",
            strike_price=70000.0,
            ofi=0.25,  # Supportive buying flow
            cross_venue_confirmed=True
        )
        order = self.brain.evaluate_packet(packet_supportive_yes)
        self.assertIsNotNone(order)
        self.assertEqual(order.action, "BUY")
        self.assertIn("YES", order.token_id)

    def test_brain_cross_venue_gate_suppresses_divergence(self):
        """Agent2Brain suppresses signals when cross_venue_confirmed is False."""
        # Explicitly enable cross-venue consensus for this enhancement unit test
        self.brain.config.enhancements.cross_venue_consensus_enabled = True

        packet = EventPacket(
            timestamp=time.time(),
            asset_id="ETH",
            spot_price=2500.0,
            spot_change_velocity_60s=0.40,
            polymarket_best_bid=0.45,
            polymarket_best_ask=0.47,
            spread_bps=42.0,
            secs_remaining=300,
            top3_depth_usdc=2000.0,
            token_id="ETH-YES",
            strike_price=2480.0,
            ofi=0.10,
            cross_venue_confirmed=False  # Divergent venues
        )
        order = self.brain.evaluate_packet(packet)
        self.assertIsNone(order)



if __name__ == "__main__":
    unittest.main()
