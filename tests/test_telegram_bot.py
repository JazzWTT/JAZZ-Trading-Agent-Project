"""
Unit tests for core.telegram_bot
Tests TelegramNotifier message generation, command handling, and HTTP queuing.
"""

import unittest
from unittest.mock import MagicMock, patch

from core.telegram_bot import TelegramNotifier
from core.models import DecisionOrder, ExecutionRecord, TradeRecord


class TestTelegramBot(unittest.TestCase):
    def setUp(self):
        self.notifier = TelegramNotifier(
            bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            chat_id="987654321",
            enabled=True
        )

    def test_initialization_and_credentials(self):
        """Verify credential assignment and dynamic updates."""
        self.assertTrue(self.notifier.enabled)
        self.assertEqual(self.notifier.chat_id, "987654321")
        self.assertIn("123456:ABC", self.notifier.base_url)

        # Dynamic update
        self.notifier.update_credentials("new_token", "new_chat", enabled=True)
        self.assertEqual(self.notifier.bot_token, "new_token")
        self.assertEqual(self.notifier.chat_id, "new_chat")
        self.assertTrue(self.notifier.enabled)

        # Disable when empty
        self.notifier.update_credentials("", "", enabled=True)
        self.assertFalse(self.notifier.enabled)

    def test_send_test_message_validation(self):
        """Verify validation when token/chat_id are empty or present."""
        empty_notifier = TelegramNotifier("", "")
        success, msg = empty_notifier.send_test_message()
        self.assertFalse(success)
        self.assertIn("must both be provided", msg)

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            success, msg = self.notifier.send_test_message()
            self.assertTrue(success)
            self.assertIn("success", msg.lower())

    def test_notify_signal_formatting(self):
        """Verify signal formatting HTML structure."""
        order = DecisionOrder(
            signal_id="SIG-BTC-YES-100",
            action="BUY",
            token_id="BTC-5M-YES",
            target_limit_price=0.48,
            calculated_edge_bps=420.0,
            max_size_shares=500.0,
            timestamp=1789078200.0,
            theoretical_probability=0.522,
            delta=0.042,
            asset_id="BTC"
        )
        with patch.object(self.notifier, "enqueue_message") as mock_enqueue:
            self.notifier.notify_signal(order)
            mock_enqueue.assert_called_once()
            html_msg = mock_enqueue.call_args[0][0]
            self.assertIn("ARBITRAGE SIGNAL DETECTED", html_msg)
            self.assertIn("BTC", html_msg)
            self.assertIn("+4.20%", html_msg)
            self.assertIn("+420 bps", html_msg)

    def test_notify_execution_formatting(self):
        """Verify execution receipt formatting."""
        record = ExecutionRecord(
            client_order_id="ORD-001",
            signal_id="SIG-001",
            token_id="ETH-5M-YES",
            side="BUY",
            price=0.45,
            size=100.0,
            order_type="LIMIT",
            submission_timestamp=1789078200.0,
            network_hash="0x1234567890abcdef1234567890abcdef",
            status="FILLED",
            attempts=1,
            latency_ms=32.4
        )
        with patch.object(self.notifier, "enqueue_message") as mock_enqueue:
            self.notifier.notify_execution(record)
            mock_enqueue.assert_called_once()
            html_msg = mock_enqueue.call_args[0][0]
            self.assertIn("ORDER FILLED", html_msg)
            self.assertIn("32.4 ms", html_msg)
            self.assertIn("$45.00 USDC", html_msg)

    def test_notify_settlement_formatting(self):
        """Verify trade settlement alert formatting."""
        trade = TradeRecord(
            trade_id="TRD-101",
            token_id="SOL-5M-YES",
            entry_price=0.40,
            exit_price=0.44,
            shares=200.0,
            duration_sec=14.5,
            slippage=0.001,
            net_pnl=7.80,
            status="SETTLED",
            entry_time=1789078000.0,
            exit_time=1789078014.5
        )
        with patch.object(self.notifier, "enqueue_message") as mock_enqueue:
            self.notifier.notify_settlement(trade, current_balance=10007.80)
            mock_enqueue.assert_called_once()
            html_msg = mock_enqueue.call_args[0][0]
            self.assertIn("POSITION SETTLED", html_msg)
            self.assertIn("+$7.80", html_msg)
            self.assertIn("+10.00%", html_msg)
            self.assertIn("$10,007.80 USDC", html_msg)

    def test_command_routing(self):
        """Verify callback routing for commands."""
        callback = MagicMock(return_value="Callback Output")
        self.notifier.command_callback = callback

        import asyncio
        asyncio.run(self.notifier._handle_command("/help"))
        # /help returns standard help menu directly without callback
        callback.assert_not_called()

        asyncio.run(self.notifier._handle_command("/status"))
        callback.assert_called_once_with("/status", [])


if __name__ == "__main__":
    unittest.main()
