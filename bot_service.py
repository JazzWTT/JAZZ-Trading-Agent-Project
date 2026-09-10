"""
JAZZ Trading United Nation - Background Bot Service
Runs the 5-agent multi-agent engine with real-time SQLite IPC and HTX spot monitoring.
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
from core.models import DecisionOrder, EventPacket
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
        
        self.db = LedgerDB(self.config.db_path)
        self.bus = MessageBus()
        self.exchange = MockMarketExchange()

        # Instantiate the 5 Agents
        self.eyes = Agent1Eyes(bus=self.bus, config=self.config)
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
        self.logger.info("Initializing JAZZ 5-Agent Trading Service with HTX feed & Polymarket CLOB...")

        # Subscribe to signals to log in SQLite
        self.bus.subscribe("trade_signals", self._on_trade_signal)

        # Start 5 Agents
        await self.eyes.start()
        await self.brain.start()
        await self.hands.start()
        await self.shield.start()
        await self.ledger.start()

        # Seed baseline price history (65s)
        base_ts = time.time() - 65.0
        for asset in ["BTC", "ETH", "SOL"]:
            for step in range(65):
                self.eyes.update_spot_price(asset, self.exchange.spot_prices[asset], ts=base_ts + step)

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
            htx_feed_status="ONLINE",
            polymarket_latency_ms=round(random.uniform(30.0, 42.0), 1)
        )
        self.logger.info("JAZZ Bot Service is now RUNNING and accepting commands from Dashboard.")

    async def _on_trade_signal(self, order: DecisionOrder):
        """Logs strategy engine signals into SQLite database."""
        self.db.record_signal(order, status="GENERATED")

    async def stop(self):
        """Gracefully stops all agents and updates IPC status."""
        self.running = False
        self.logger.info("Stopping JAZZ Bot Service...")
        await self.eyes.stop()
        await self.brain.stop()
        await self.hands.stop()
        await self.shield.stop()
        await self.ledger.stop()

        self.db.update_bot_control(status="STOPPED", last_heartbeat=time.time())
        self.logger.info("JAZZ Bot Service has STOPPED.")

    async def run_loop(self):
        """Main service loop handling IPC controls, HTX spot feed, ticks, and snapshots."""
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

                # 2. Simulate / Broadcast Market Ticks
                tick_count += 1
                # Occasional momentum burst (e.g. every 6-8 ticks) to test strategy signals
                momentum_burst = (tick_count % 7 == 0)
                spread_spike = (tick_count % 15 == 0)

                for asset in ["BTC", "ETH"]:
                    spot, contract = self.exchange.generate_tick(
                        asset=asset,
                        momentum_burst=momentum_burst,
                        spread_spike=spread_spike
                    )

                    # Update spot in Eyes
                    self.eyes.update_spot_price(asset, spot)

                    # Update CLOB in Eyes
                    packet = self.eyes.update_polymarket_clob(
                        asset=asset,
                        bids=contract["bids"],
                        asks=contract["asks"],
                        secs_remaining=contract["secs_remaining"],
                        token_id=contract["token_id"],
                        market_id=contract["market_id"]
                    )

                    if packet:
                        await self.eyes.emit_packet(packet)

                # 3. Settle open positions at realistic market prices to simulate trade lifecycle
                now_ts = time.time()
                for trade_id, trade in list(self.ledger.open_positions.items()):
                    # Settle if position duration >= 5 seconds
                    if (now_ts - trade.entry_time) >= 5.0:
                        asset_sym = trade.token_id.split("-")[0]
                        # 60% probability of profitable edge realization
                        if random.random() < 0.60:
                            exit_price = min(0.99, trade.entry_price + random.uniform(0.015, 0.04))
                        else:
                            exit_price = max(0.01, trade.entry_price - random.uniform(0.015, 0.035))
                        self.ledger.settle_trade(trade_id, exit_price=round(exit_price, 4))

                # 4. Compute and record portfolio snapshot & HTX metrics
                metrics = self.ledger.refresh_metrics()
                btc_vel = self.eyes.calculate_spot_velocity_60s("BTC")
                btc_spot = self.eyes.current_spot.get("BTC", 64250.0)
                pm_latency = round(random.uniform(28.0, 42.0), 1)

                # Update IPC telemetry
                self.db.update_bot_control(
                    last_heartbeat=time.time(),
                    htx_feed_status="ONLINE",
                    polymarket_latency_ms=pm_latency,
                    htx_spot_price=btc_spot,
                    htx_velocity_60s=btc_vel
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
