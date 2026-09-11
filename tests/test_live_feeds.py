"""
Unit tests for core.dns_resolver and core.live_feeds
Verifies DNS resolution, strike parsing, CLOB book processing, and Agent 1 integration.
"""

import socket
import unittest
from unittest.mock import MagicMock, patch

from core.dns_resolver import patch_dns, unpatch_dns, resolve_domain, query_dns_udp
from core.live_feeds import (
    LiveSpotFeedManager,
    LivePolymarketFeedManager,
    extract_strike_from_question,
    DEFAULT_TARGET_MARKETS
)
from core.message_bus import MessageBus
from agents.agent1_eyes import Agent1Eyes


class TestLiveFeedsAndDNS(unittest.TestCase):
    def setUp(self):
        unpatch_dns()

    def tearDown(self):
        unpatch_dns()

    def test_dns_resolver_resolves_clean_ip(self):
        """DNS resolver should never return Malaysian ISP sinkhole IP (175.139.x.x)."""
        ip = resolve_domain("gamma-api.polymarket.com")
        self.assertTrue(ip.startswith("172.") or ip.startswith("104.") or ip.startswith("198."))
        self.assertFalse(ip.startswith("175.139."))

    def test_dns_monkey_patch_and_unpatch(self):
        """patch_dns() should intercept socket.getaddrinfo; unpatch_dns() should restore it."""
        orig_fn = socket.getaddrinfo
        patch_dns()
        self.assertNotEqual(socket.getaddrinfo, orig_fn)
        
        # Calling getaddrinfo for target domain should resolve via clean IP
        addrs = socket.getaddrinfo("gamma-api.polymarket.com", 443)
        self.assertTrue(len(addrs) > 0)
        target_ip = addrs[0][4][0]
        self.assertFalse(target_ip.startswith("175.139."))

        unpatch_dns()
        self.assertEqual(socket.getaddrinfo, orig_fn)

    def test_extract_strike_from_question(self):
        """Regex helper should extract strike price from various question formats."""
        self.assertEqual(extract_strike_from_question("Will Bitcoin reach $95,000 by December 31, 2026?"), 95000.0)
        self.assertEqual(extract_strike_from_question("Will Ethereum reach $2,750 by December 31, 2026?"), 2750.0)
        self.assertEqual(extract_strike_from_question("Will Solana reach $140 by December 31, 2026?"), 140.0)
        self.assertEqual(extract_strike_from_question("Will XRP dip to $1.25 by 2026?"), 1.25)
        self.assertEqual(extract_strike_from_question("No dollar sign here"), 0.0)

    def test_clob_order_book_processing(self):
        """CLOB manager should parse initial book snapshots and price_change deltas correctly."""
        on_book = MagicMock()
        pm_mgr = LivePolymarketFeedManager(on_book_update=on_book)
        pm_mgr.target_markets = {
            "BTC": {
                "asset": "BTC",
                "market_id": "test_mkt",
                "question": "Will BTC reach $90k?",
                "strike_price": 90000.0,
                "token_id_yes": "TOKEN_BTC_YES",
                "token_id_no": "TOKEN_BTC_NO",
                "evaluation_secs_remaining": 300
            }
        }
        pm_mgr.token_to_asset = {
            "TOKEN_BTC_YES": ("BTC", "YES"),
            "TOKEN_BTC_NO": ("BTC", "NO")
        }

        # 1. Simulate full L2 book snapshot
        snapshot = {
            "event_type": "book",
            "asset_id": "TOKEN_BTC_YES",
            "bids": [{"price": "0.40", "size": "1000"}, {"price": "0.42", "size": "2000"}],
            "asks": [{"price": "0.45", "size": "1500"}, {"price": "0.48", "size": "3000"}],
            "timestamp": "1789078200000"
        }
        pm_mgr._process_clob_item(snapshot, now=1789078200.0)

        book = pm_mgr.books["TOKEN_BTC_YES"]
        # Bids must be sorted descending (best bid first = 0.42)
        self.assertEqual(book["best_bid"], 0.42)
        # Asks must be sorted ascending (best ask first = 0.45)
        self.assertEqual(book["best_ask"], 0.45)
        self.assertEqual(book["mid_price"], 0.435)
        # Spread = 0.45 - 0.42 = 0.03 -> spread_bps = (0.03 / 0.435) * 10000 = ~689.66
        self.assertAlmostEqual(book["spread_bps"], 689.66, places=1)
        on_book.assert_called_once()

        # 2. Simulate incremental price_change delta
        delta = {
            "event_type": "price_change",
            "price_changes": [
                {
                    "asset_id": "TOKEN_BTC_YES",
                    "best_bid": "0.43",
                    "best_ask": "0.44",
                    "side": "BUY"
                }
            ]
        }
        pm_mgr._process_clob_item(delta, now=1789078201.0)
        updated_book = pm_mgr.books["TOKEN_BTC_YES"]
        self.assertEqual(updated_book["best_bid"], 0.43)
        self.assertEqual(updated_book["best_ask"], 0.44)
        self.assertEqual(on_book.call_count, 2)

    def test_agent1_attach_live_feeds(self):
        """Agent 1 should update prices and emit packets when fed by live managers."""
        bus = MessageBus()
        eyes = Agent1Eyes(bus=bus)
        spot_mgr = LiveSpotFeedManager()
        pm_mgr = LivePolymarketFeedManager()

        eyes.attach_live_feeds(spot_mgr, pm_mgr)
        self.assertIsNotNone(spot_mgr.on_tick)
        self.assertIsNotNone(pm_mgr.on_book_update)

        # Trigger tick
        spot_mgr.on_tick("BTC", 77250.0, 1000.0)
        self.assertEqual(eyes.current_spot["BTC"], 77250.0)


if __name__ == "__main__":
    unittest.main()
