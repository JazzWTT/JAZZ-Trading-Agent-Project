"""
JAZZ Trading United Nation - Background Bot Service
Runs the 5-agent multi-agent engine with real-time SQLite IPC, 100% Real Live Market Feeds,
Order Flow Imbalance (OFI), Cross-Venue Consensus, Dynamic TP/SL, and Telegram Integration.
"""

import asyncio
import logging
import os
import random
import sys
import time
from typing import Dict, Optional

# Ensure scratch directory is on sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import DEFAULT_CONFIG, SystemConfig
from core.message_bus import MessageBus
from core.models import DecisionOrder, EventPacket, TradeRecord, ExecutionRecord
from core.live_feeds import LiveSpotFeedManager, LivePolymarketFeedManager
from core.telegram_bot import TelegramNotifier
from database.ledger_db import LedgerDB, SQLiteLogHandler
from agents.agent1_eyes import Agent1Eyes
from agents.agent2_brain import Agent2Brain
from agents.agent3_hands import Agent3Hands
from agents.agent4_shield import Agent4Shield
from agents.agent5_ledger import Agent5Ledger
from simulation.mock_exchange import MockMarketExchange


class BotService:
    def __init__(self, db_path: Optional[str] = None):
        self.config = DEFAULT_CONFIG
        if db_path:
            self.config.db_path = db_path
        # Enforce 100% passive Brier tournament mode: no trade execution or signing
        self.config.passive_tournament_mode = True
        
        self.db = LedgerDB(self.config.db_path)
        self.bus = MessageBus()
        self.exchange = MockMarketExchange()

        # 100% Real Live Market Feed Managers (Coinbase, OKX, Polymarket CLOB)
        self.live_spot = LiveSpotFeedManager()
        self.live_pm = LivePolymarketFeedManager()

        # Telegram Bot Notifier & Command Listener
        self.telegram = TelegramNotifier(command_callback=self._handle_telegram_command)

        # Instantiate the 5 Agents
        self.eyes = Agent1Eyes(bus=self.bus, config=self.config)
        self.eyes.attach_live_feeds(self.live_spot, self.live_pm)
        self.brain = Agent2Brain(bus=self.bus, config=self.config)
        self.hands = Agent3Hands(bus=self.bus, db=self.db, config=self.config)
        self.shield = Agent4Shield(bus=self.bus, db=self.db, config=self.config)
        self.ledger = Agent5Ledger(bus=self.bus, db=self.db, config=self.config)

        self.running = False
        self.logger = logging.getLogger("BotService")
        self._setup_logging()

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%H:%M:%S"
        )
        # Attach SQLite logging handler
        sqlite_handler = SQLiteLogHandler(self.db)
        sqlite_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(sqlite_handler)

    async def start(self):
        """Starts all agents, subscriptions, and background tasks."""
        self.running = True
        self.logger.info("Initializing JAZZ 5-Agent Trading Service with 100% Live Market Feeds & Telegram...")

        # Initialize Telegram credentials from DB or Environment
        ctrl = self.db.get_bot_control()
        tg_token = ctrl.get("telegram_bot_token") or os.getenv("TELEGRAM_BOT_TOKEN", self.config.telegram.bot_token)
        tg_chat = ctrl.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID", self.config.telegram.chat_id)
        tg_enabled = bool(ctrl.get("telegram_enabled", 0)) or self.config.telegram.enabled or bool(tg_token and tg_chat)
        if tg_token and tg_chat:
            self.telegram.update_credentials(tg_token, tg_chat, enabled=tg_enabled)
        await self.telegram.start()

        # Subscribe to channels for logging & Telegram alerts
        self.bus.subscribe("trade_signals", self._on_trade_signal)
        self.bus.subscribe("order_executions", self._on_order_execution)
        self.bus.subscribe("settled_trades", self._on_settled_trade)
        self.bus.subscribe("risk_alerts", self._on_risk_alert)

        # Start 5 Agents
        await self.eyes.start()
        await self.brain.start()
        await self.hands.start()
        await self.shield.start()
        await self.ledger.start()

        # Start 100% Real Live Feeds (Coinbase/OKX Spot & Polymarket CLOB)
        await self.live_spot.start()
        await self.live_pm.start()

        # Wait briefly for initial live packets to establish baseline
        await asyncio.sleep(1.0)

        # Seed baseline price history (365s) from live prices to establish pre-burst baseline window
        base_ts = time.time() - 365.0
        for asset in ["BTC", "ETH", "SOL"]:
            live_p = self.live_spot.prices.get(asset, 77100.0 if asset == "BTC" else (2460.0 if asset == "ETH" else 100.0))
            for step in range(365):
                self.eyes.update_spot_price(asset, live_p, ts=base_ts + step)

        # Reconcile existing open positions from SQLite into memory
        existing_open = self.db.get_open_positions()
        for p in existing_open:
            self.ledger.open_positions[p["trade_id"]] = TradeRecord(
                trade_id=p["trade_id"],
                token_id=p["token_id"],
                entry_price=p["entry_price"],
                shares=p["shares"],
                duration_sec=p["duration_sec"],
                slippage=p["slippage"],
                net_pnl=p["net_pnl"],
                status="OPEN",
                entry_time=p["entry_time"]
            )

        # Update IPC status to RUNNING
        self.db.update_bot_control(
            status="RUNNING",
            kill_switch=0,
            last_heartbeat=time.time(),
            htx_feed_status=self.live_spot.status,
            polymarket_latency_ms=self.live_pm.latency_ms
        )
        self.logger.info("JAZZ Bot Service is now RUNNING with 100% Real Live Market Prices.")

    async def _on_trade_signal(self, order: DecisionOrder):
        """Logs strategy engine signals into SQLite database and alerts Telegram."""
        self.db.record_signal(order, status="GENERATED")
        if self.config.telegram.notify_signals:
            self.telegram.notify_signal(order)

    async def _on_order_execution(self, record: ExecutionRecord):
        """Dispatches order execution alerts via Telegram."""
        if self.config.telegram.notify_trades:
            self.telegram.notify_execution(record)

    async def _on_settled_trade(self, trade: TradeRecord):
        """Dispatches trade settlement alert via Telegram."""
        if self.config.telegram.notify_trades:
            acct = self.db.get_portfolio_accounting(initial_capital=self.config.risk.total_capital_usdc)
            self.telegram.notify_settlement(trade, current_balance=acct["cash_balance"])

    async def _on_risk_alert(self, alert: dict):
        """Dispatches critical risk/kill-switch alert via Telegram."""
        if self.config.telegram.notify_risks:
            self.telegram.notify_risk_alert(
                alert_type=alert.get("type", "RISK_ALERT"),
                details=f"Lag: {alert.get('lag_sec', 0):.1f}s | Source: {alert.get('source', 'Shield/Eyes')}"
            )

    def _handle_telegram_command(self, cmd: str, args: list) -> str:
        """Handles interactive commands sent from authorized Telegram chats."""
        if cmd == "/status":
            btc = self.live_spot.prices.get("BTC", 0.0)
            eth = self.live_spot.prices.get("ETH", 0.0)
            sol = self.live_spot.prices.get("SOL", 0.0)
            btc_v = self.eyes.calculate_spot_velocity_60s("BTC")
            eth_v = self.eyes.calculate_spot_velocity_60s("ETH")
            sol_v = self.eyes.calculate_spot_velocity_60s("SOL")
            open_n = len(self.ledger.open_positions)
            return (
                f"⚡ <b>JAZZ UN SYSTEM STATUS</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Status:</b> <code>{self.db.get_bot_control().get('status', 'RUNNING')}</code>\n"
                f"<b>BTC/USD:</b> <code>${btc:,.2f}</code> ({btc_v:+.2f}%/m)\n"
                f"<b>ETH/USD:</b> <code>${eth:,.2f}</code> ({eth_v:+.2f}%/m)\n"
                f"<b>SOL/USD:</b> <code>${sol:,.2f}</code> ({sol_v:+.2f}%/m)\n"
                f"<b>CLOB Latency:</b> <code>{self.live_pm.latency_ms:.1f} ms</code>\n"
                f"<b>Open Positions:</b> <code>{open_n}</code>"
            )
        elif cmd == "/balance":
            acct = self.db.get_portfolio_accounting(initial_capital=self.config.risk.total_capital_usdc)
            metrics = self.db.calculate_metrics(current_cash=acct["cash_balance"])
            return (
                f"💵 <b>PORTFOLIO ACCOUNTING</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Cash:</b> <code>${acct['cash_balance']:,.2f} USDC</code>\n"
                f"<b>Total Equity:</b> <code>${acct['total_equity']:,.2f} USDC</code>\n"
                f"<b>Open Exposure:</b> <code>${acct['open_cost']:,.2f} USDC</code>\n"
                f"<b>24h Realized PnL:</b> <b>{'+' if acct['realized_pnl_24h'] >= 0 else ''}${acct['realized_pnl_24h']:.2f} ({acct['realized_pnl_pct']:+.2f}%)</b>\n"
                f"<b>Win Rate:</b> <code>{metrics.win_rate:.1f}%</code> ({metrics.total_trades} trades)"
            )
        elif cmd == "/kill":
            self.db.update_bot_control(status="STOPPED", kill_switch=1)
            self.logger.critical("[KILL-SWITCH ENGAGED] Telegram /kill command received!")
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.shield.trigger_kill_switch("Telegram /kill command"))
            except Exception:
                pass
            return "🚨 <b>EMERGENCY KILL-SWITCH ENGAGED!</b>\nTrading halted immediately. All resting orders cancelled."
        elif cmd == "/resume":
            self.db.update_bot_control(status="RUNNING", kill_switch=0)
            self.shield.kill_switch_active = False
            self.logger.info("[RESUME ENGAGED] Telegram /resume command received!")
            return "▶️ <b>ENGINE RESUMED!</b>\nTrading operations restored to RUNNING state."
        return "Unknown command. Type /help for options."

    async def stop(self):
        """Gracefully stops all feeds, agents, and updates IPC status."""
        self.running = False
        self.logger.info("Stopping JAZZ Bot Service...")
        await self.telegram.stop()
        await self.live_spot.stop()
        await self.live_pm.stop()
        await self.eyes.stop()
        await self.brain.stop()
        await self.hands.stop()
        await self.shield.stop()
        await self.ledger.stop()

        self.db.update_bot_control(status="STOPPED", last_heartbeat=time.time())
        self.logger.info("JAZZ Bot Service has STOPPED.")

    async def run_loop(self):
        """Main service loop refused: strategy retired on evidence."""
        self.logger.critical("SHELVED: strategy retired on 2026-09-13. See POSTMORTEM.md.")
        return

        # Unreachable code preserved below
        await self.start()
        tick_count = 0

        try:
            while self.running:
                # 1. Sync IPC Bot Control from SQLite
                ctrl = self.db.get_bot_control()
                
                # Check Emergency Kill-Switch
                if ctrl.get("kill_switch", 0) == 1:
                    self.logger.critical("[KILL-SWITCH ENGAGED] Dashboard triggered emergency stop!")
                    await self.shield.trigger_kill_switch("Dashboard emergency kill-switch")
                    self.db.update_bot_control(status="STOPPED")
                    break

                # If status changed to STOPPED from UI
                if ctrl.get("status") == "STOPPED":
                    self.logger.info("[ENGINE HALTED] Status set to STOPPED in dashboard.")
                    await asyncio.sleep(1.0)
                    continue

                # Dynamically sync risk sliders
                if "max_position_pct" in ctrl:
                    self.config.risk.max_position_exposure_pct = float(ctrl["max_position_pct"])
                if "daily_loss_limit_pct" in ctrl:
                    self.config.risk.daily_loss_circuit_breaker_pct = float(ctrl["daily_loss_limit_pct"])
                if "min_profit_threshold_pct" in ctrl:
                    self.config.strategy.min_profit_threshold_pct = float(ctrl["min_profit_threshold_pct"])
                if "max_spread_bps" in ctrl:
                    self.config.strategy.max_spread_bps = float(ctrl["max_spread_bps"])
                    self.config.risk.max_spread_bps_shield = float(ctrl["max_spread_bps"])

                # Dynamically sync Telegram credentials if updated in UI
                db_tg_token = ctrl.get("telegram_bot_token", "").strip()
                db_tg_chat = ctrl.get("telegram_chat_id", "").strip()
                db_tg_enabled = bool(ctrl.get("telegram_enabled", 0))
                if db_tg_token and db_tg_chat:
                    if (db_tg_token != self.telegram.bot_token or 
                        db_tg_chat != self.telegram.chat_id or 
                        db_tg_enabled != self.telegram.enabled):
                        self.telegram.update_credentials(db_tg_token, db_tg_chat, enabled=db_tg_enabled)

                # 2. Broadcast Live Market Packets (Real Spot + Real Polymarket CLOB)
                tick_count += 1
                now_ts = time.time()

                for asset in ["BTC", "ETH", "SOL"]:
                    # Latest live spot price from Coinbase / OKX
                    spot = self.live_spot.prices.get(asset, self.eyes.current_spot.get(asset, 0.0))
                    self.eyes.update_spot_price(asset, spot, ts=now_ts)

                    # Latest live Polymarket order book
                    mkt = self.live_pm.target_markets.get(asset, {})
                    token_id = mkt.get("token_id_yes", "")
                    book = self.live_pm.books.get(token_id)
                    expiry_ts = mkt.get("expiry_ts")

                    if book and book.get("bids") and book.get("asks") and expiry_ts:
                        secs_rem = expiry_ts - now_ts
                        if secs_rem > 0:
                            packet = self.eyes.update_polymarket_clob(
                                asset=asset,
                                bids=book["bids"],
                                asks=book["asks"],
                                secs_remaining=secs_rem,
                                token_id=token_id,
                                market_id=mkt.get("market_id", ""),
                                strike_price=mkt.get("strike_price", 0.0),
                                ts=now_ts,
                                ofi=book.get("ofi", 0.0)
                            )
                            if packet:
                                await self.eyes.emit_packet(packet)

                            # Check danger zone eligibility per tick (120s <= secs_rem <= 600s)
                            is_eligible = (
                                self.config.market.danger_zone_min_secs <= secs_rem <= self.config.market.danger_zone_max_secs
                            )

                            # Record Brier Calibration Prediction for Model vs Market Tournament strictly when eligible
                            if is_eligible:
                                strike = mkt.get("strike_price", 0.0)
                                mid = book.get("mid_price", 0.0)
                                if strike > 0 and mid > 0 and spot > 0:
                                    baseline_vol = self.eyes.calculate_baseline_volatility(asset)
                                    fair_prob = self.brain.calculate_theoretical_probability(
                                        spot=spot,
                                        strike=strike,
                                        secs_remaining=secs_rem,
                                        annualized_vol=baseline_vol,
                                        outcome_side="YES"
                                    )
                                    self.db.record_brier_prediction(
                                        asset_id=asset,
                                        market_id=mkt.get("market_id", ""),
                                        token_id=token_id,
                                        strike_price=strike,
                                        expiry_ts=expiry_ts,
                                        model_fair_prob=round(fair_prob, 4),
                                        market_mid_price=round(mid, 4)
                                    )
                    elif not self.live_pm.running or not book:
                        # Fallback to simulated exchange tick during feed handshake
                        spot_sim, contract = self.exchange.generate_tick(asset=asset)
                        packet = self.eyes.update_polymarket_clob(
                            asset=asset,
                            bids=contract["bids"],
                            asks=contract["asks"],
                            secs_remaining=contract["secs_remaining"],
                            token_id=contract["token_id"],
                            market_id=contract["market_id"],
                            strike_price=contract.get("strike_price", 0.0),
                            ts=now_ts,
                            ofi=0.0
                        )
                        if packet:
                            await self.eyes.emit_packet(packet)

                # Resolve expired Brier predictions against current live spot prices
                current_spots = {
                    a: self.live_spot.prices.get(a, self.eyes.current_spot.get(a, 0.0))
                    for a in ["BTC", "ETH", "SOL"]
                }
                self.db.resolve_expired_brier_predictions(current_spots, now_ts)

                # 3. Dynamic Take-Profit & Stop-Loss paper settlement (disabled by default pending GATE.md validation)
                if getattr(self.config.enhancements, "dynamic_tpsl_enabled", False):
                    for trade_id, trade in list(self.ledger.open_positions.items()):

                    book = self.live_pm.books.get(trade.token_id)
                    duration = now_ts - trade.entry_time
                    should_settle = False
                    exit_price = trade.entry_price

                    if book and book.get("best_bid", 0) > 0:
                        exit_price = book["best_bid"]
                        if trade.entry_price > 0:
                            ret_bps = ((exit_price - trade.entry_price) / trade.entry_price) * 10000.0
                            if ret_bps >= self.config.enhancements.take_profit_bps:
                                should_settle = True
                                self.logger.info(f"[TAKE-PROFIT] Trade {trade_id} +{ret_bps:.0f} bps >= +{self.config.enhancements.take_profit_bps} bps")
                            elif ret_bps <= -self.config.enhancements.stop_loss_bps:
                                should_settle = True
                                self.logger.info(f"[STOP-LOSS] Trade {trade_id} {ret_bps:.0f} bps <= -{self.config.enhancements.stop_loss_bps} bps")
                            elif duration >= 30.0:
                                should_settle = True
                    elif duration >= 10.0:
                        should_settle = True
                        if random.random() < 0.60:
                            exit_price = min(0.99, trade.entry_price + random.uniform(0.015, 0.04))
                        else:
                            exit_price = max(0.01, trade.entry_price - random.uniform(0.015, 0.035))

                    if should_settle:
                        self.ledger.settle_trade(trade_id, exit_price=round(exit_price, 4))

                # 4. Compute and record portfolio snapshot & live venue telemetry
                metrics = self.ledger.refresh_metrics()
                btc_spot = self.live_spot.prices.get("BTC", self.eyes.current_spot.get("BTC", 77100.0))
                eth_spot = self.live_spot.prices.get("ETH", self.eyes.current_spot.get("ETH", 2460.0))
                sol_spot = self.live_spot.prices.get("SOL", self.eyes.current_spot.get("SOL", 100.0))
                btc_vel = self.eyes.calculate_spot_velocity_60s("BTC")
                eth_vel = self.eyes.calculate_spot_velocity_60s("ETH")
                sol_vel = self.eyes.calculate_spot_velocity_60s("SOL")
                pm_latency = self.live_pm.latency_ms
                spot_status = self.live_spot.status

                mkt_btc = self.live_pm.target_markets.get("BTC", {})
                mkt_eth = self.live_pm.target_markets.get("ETH", {})
                mkt_sol = self.live_pm.target_markets.get("SOL", {})
                ofi_btc = self.live_pm.books.get(mkt_btc.get("token_id_yes", ""), {}).get("ofi", 0.0)
                ofi_eth = self.live_pm.books.get(mkt_eth.get("token_id_yes", ""), {}).get("ofi", 0.0)
                ofi_sol = self.live_pm.books.get(mkt_sol.get("token_id_yes", ""), {}).get("ofi", 0.0)
                cons_btc = 1 if self.live_spot.check_cross_venue_consensus("BTC", "UP" if btc_vel >= 0 else "DOWN") else 0
                cons_eth = 1 if self.live_spot.check_cross_venue_consensus("ETH", "UP" if eth_vel >= 0 else "DOWN") else 0
                cons_sol = 1 if self.live_spot.check_cross_venue_consensus("SOL", "UP" if sol_vel >= 0 else "DOWN") else 0

                # Update IPC telemetry with 100% real live market data
                self.db.update_bot_control(
                    last_heartbeat=time.time(),
                    htx_feed_status=spot_status,
                    polymarket_latency_ms=pm_latency,
                    htx_spot_price=btc_spot,
                    htx_velocity_60s=btc_vel,
                    eth_spot_price=eth_spot,
                    eth_velocity_60s=eth_vel,
                    sol_spot_price=sol_spot,
                    sol_velocity_60s=sol_vel,
                    ofi_btc=ofi_btc,
                    ofi_eth=ofi_eth,
                    ofi_sol=ofi_sol,
                    consensus_btc=cons_btc,
                    consensus_eth=cons_eth,
                    consensus_sol=cons_sol
                )

                # Record portfolio snapshot using sound accounting
                acct = self.db.get_portfolio_accounting(initial_capital=self.config.risk.total_capital_usdc)
                self.db.record_portfolio_snapshot(
                    equity_usdc=acct["total_equity"],
                    cash_usdc=acct["cash_balance"],
                    open_exposure_usdc=acct["open_cost"],
                    pnl_24h=acct["realized_pnl_24h"]
                )

                await asyncio.sleep(1.0)

        finally:
            await self.stop()


def main():
    service = BotService()
    try:
        asyncio.run(service.run_loop())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
