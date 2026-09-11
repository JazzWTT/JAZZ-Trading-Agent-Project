"""
Telegram Bot Integration & Remote Command Dispatcher
Provides real-time mobile push notifications for:
- Arbitrage trade signals (Black-Scholes vs. Polymarket ask)
- Shield risk checks & position sizing
- Order executions & EIP-712 receipts
- Settled trade P&L realizations
- Emergency kill-switch / daily loss circuit breaker alerts
Also listens for remote commands (/status, /balance, /kill, /resume).
"""

import asyncio
import html
import json
import logging
import time
from typing import Callable, Dict, Optional, Any, Tuple
import requests

from core.models import DecisionOrder, ExecutionRecord, TradeRecord

logger = logging.getLogger("TelegramBot")


class TelegramNotifier:
    """
    Non-blocking, queue-based Telegram notification client.
    Runs HTTP requests in a background executor so network latency
    never degrades the high-frequency trading pipeline.
    """
    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        enabled: bool = False,
        command_callback: Optional[Callable[[str, list], str]] = None
    ):
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        self.enabled = enabled and bool(self.bot_token and self.chat_id)
        self.command_callback = command_callback
        
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.running: bool = False
        self._worker_task: Optional[asyncio.Task] = None
        self._polling_task: Optional[asyncio.Task] = None
        self._last_update_id: int = 0
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    def update_credentials(self, bot_token: str, chat_id: str, enabled: bool = True):
        """Dynamically update bot credentials without restarting."""
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        self.enabled = enabled and bool(self.bot_token and self.chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        logger.info(f"TelegramNotifier credentials updated (Enabled: {self.enabled})")

    async def start(self):
        """Starts the notification dispatcher and command polling tasks."""
        self.running = True
        self._worker_task = asyncio.create_task(self._dispatch_worker())
        if self.enabled and self.command_callback:
            self._polling_task = asyncio.create_task(self._poll_updates())
        logger.info(f"TelegramNotifier started (Active: {self.enabled})")

    async def stop(self):
        """Stops the dispatcher and polling tasks."""
        self.running = False
        if self._worker_task:
            self._worker_task.cancel()
        if self._polling_task:
            self._polling_task.cancel()
        logger.info("TelegramNotifier stopped.")

    def enqueue_message(self, text: str, parse_mode: str = "HTML"):
        """Enqueues a message for background delivery (non-blocking)."""
        if not self.enabled:
            return
        try:
            self.queue.put_nowait((text, parse_mode))
        except asyncio.QueueFull:
            logger.warning("Telegram notification queue full; dropping message.")

    async def _dispatch_worker(self):
        """Worker loop consuming messages and posting to Telegram with rate-limiting."""
        while self.running:
            try:
                text, parse_mode = await self.queue.get()
                await asyncio.to_thread(self._send_http_message, text, parse_mode)
                self.queue.task_done()
                # Rate limit to avoid Telegram 429 Too Many Requests
                await asyncio.sleep(0.3)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Telegram dispatch worker: {e}")
                await asyncio.sleep(1.0)

    def _send_http_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Synchronous HTTP call to Telegram sendMessage endpoint."""
        if not self.bot_token or not self.chat_id:
            return False
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        try:
            r = requests.post(url, json=payload, timeout=5.0)
            if r.status_code == 200:
                return True
            else:
                logger.warning(f"Telegram API error {r.status_code}: {r.text}")
                return False
        except Exception as e:
            logger.warning(f"Failed to post message to Telegram: {e}")
            return False

    def send_test_message(self) -> Tuple[bool, str]:
        """Synchronous immediate test ping for UI verification."""
        if not self.bot_token or not self.chat_id:
            return False, "Bot Token and Chat ID must both be provided."
        text = (
            "⚡ <b>JAZZ Trading UN — System Connected!</b>\n\n"
            "✅ <i>Telegram real-time alerts successfully linked to your trading terminal.</i>\n"
            f"🕒 Timestamp: <code>{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}</code>\n"
            "🛡️ Guard: <b>Paper-Trading (Zero Real Funds At Risk)</b>"
        )
        success = self._send_http_message(text)
        if success:
            return True, "Test alert sent successfully to Telegram!"
        return False, "Failed to connect to Telegram. Please check your Bot Token and Chat ID."

    # =========================================================================
    # PRE-FORMATTED TELEGRAM ALERT DISPATCHERS
    # =========================================================================
    def notify_signal(self, order: DecisionOrder):
        """Dispatches an arbitrage signal notification."""
        side_emoji = "🟢" if "YES" in order.token_id else "🔴"
        text = (
            f"🎯 <b>ARBITRAGE SIGNAL DETECTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Asset:</b> <code>{order.asset_id}</code> | <b>Action:</b> {side_emoji} <b>{order.action}</b>\n"
            f"<b>Token:</b> <code>{order.token_id}</code>\n"
            f"<b>BS Model Prob:</b> <code>{order.theoretical_probability*100:.1f}%</code>\n"
            f"<b>Polymarket Ask:</b> <code>${order.target_limit_price:.4f}</code>\n"
            f"<b>Edge:</b> <b>+{order.delta*100:.2f}%</b> (+{order.calculated_edge_bps:.0f} bps)\n"
            f"<b>Proposed Size:</b> <code>{order.max_size_shares:.1f} shares</code>\n"
            f"🕒 <i>{time.strftime('%H:%M:%S UTC', time.gmtime(order.timestamp))}</i>"
        )
        self.enqueue_message(text)

    def notify_execution(self, record: ExecutionRecord):
        """Dispatches an order execution receipt."""
        status_emoji = "✅" if record.status == "FILLED" else ("⏳" if record.status == "POSTED" else "❌")
        text = (
            f"{status_emoji} <b>ORDER {record.status}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Token:</b> <code>{record.token_id}</code>\n"
            f"<b>Side:</b> <code>{record.side}</code> | <b>Type:</b> <code>{record.order_type}</code>\n"
            f"<b>Filled Price:</b> <code>${record.price:.4f}</code>\n"
            f"<b>Filled Size:</b> <code>{record.size:.1f} shares</code>\n"
            f"<b>Notional Cost:</b> <code>${record.price * record.size:.2f} USDC</code>\n"
            f"<b>Execution Latency:</b> <code>{record.latency_ms:.1f} ms</code>\n"
            f"<b>EIP-712 Sig:</b> <code>{record.network_hash[:16]}...</code>"
        )
        self.enqueue_message(text)

    def notify_settlement(self, trade: TradeRecord, current_balance: float):
        """Dispatches a trade settlement and realized P&L alert."""
        pnl_emoji = "💰" if trade.net_pnl >= 0 else "🔻"
        pct_return = ((trade.exit_price - trade.entry_price) / trade.entry_price * 100.0) if trade.entry_price > 0 else 0.0
        text = (
            f"{pnl_emoji} <b>POSITION SETTLED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Trade ID:</b> <code>{trade.trade_id}</code>\n"
            f"<b>Token:</b> <code>{trade.token_id}</code>\n"
            f"<b>Entry:</b> <code>${trade.entry_price:.4f}</code> ➔ <b>Exit:</b> <code>${trade.exit_price:.4f}</code>\n"
            f"<b>Duration:</b> <code>{trade.duration_sec:.1f}s</code>\n"
            f"<b>Realized P&L:</b> <b>{'+' if trade.net_pnl >= 0 else ''}${trade.net_pnl:.2f} ({pct_return:+.2f}%)</b>\n"
            f"<b>Portfolio Cash:</b> <code>${current_balance:,.2f} USDC</code>"
        )
        self.enqueue_message(text)

    def notify_risk_alert(self, alert_type: str, details: str):
        """Dispatches critical risk, kill-switch, or circuit breaker alerts."""
        text = (
            f"🚨 <b>CRITICAL RISK ALERT: {html.escape(alert_type)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{html.escape(details)}\n"
            f"🕒 <i>{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}</i>\n"
            f"⚠️ <b>Action Taken:</b> Orders halted / resting cancelled."
        )
        self.enqueue_message(text)

    # =========================================================================
    # INTERACTIVE COMMAND POLLING LOOP (/status, /balance, /kill, /resume)
    # =========================================================================
    async def _poll_updates(self):
        """Polls Telegram getUpdates endpoint for incoming user commands."""
        while self.running:
            try:
                url = f"{self.base_url}/getUpdates?offset={self._last_update_id + 1}&timeout=10"
                r = await asyncio.to_thread(requests.get, url, timeout=15.0)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("ok") and data.get("result"):
                        for upd in data["result"]:
                            self._last_update_id = max(self._last_update_id, upd["update_id"])
                            msg = upd.get("message", {})
                            text = msg.get("text", "").strip()
                            chat = str(msg.get("chat", {}).get("id", ""))
                            
                            # Security: Only respond to authorized chat_id
                            if chat == self.chat_id and text.startswith("/"):
                                await self._handle_command(text)
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Telegram polling error: {e}")
                await asyncio.sleep(3.0)

    async def _handle_command(self, cmd_text: str):
        """Parses and executes Telegram commands."""
        parts = cmd_text.split()
        cmd = parts[0].lower().split("@")[0]  # Remove bot username if present
        args = parts[1:]

        if cmd in ["/start", "/help"]:
            reply = (
                "⚡ <b>JAZZ Trading UN — Bot Commands</b>\n\n"
                "📊 <b>/status</b> — System health, live prices & open positions\n"
                "💵 <b>/balance</b> — Portfolio cash, open exposure & 24h P&L\n"
                "🛑 <b>/kill</b> — Emergency Kill-Switch (Halts trading immediately)\n"
                "▶️ <b>/resume</b> — Resume trading engine after halt\n"
                "ℹ️ <b>/help</b> — Display this command menu"
            )
        elif self.command_callback:
            # Delegate command execution to BotService callback
            reply = await asyncio.to_thread(self.command_callback, cmd, args)
        else:
            reply = f"Unknown command: <code>{html.escape(cmd)}</code>. Type /help for options."

        self.enqueue_message(reply)
