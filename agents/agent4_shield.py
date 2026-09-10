"""
Agent 4: Risk Management Guardrails (The Shield)
Role: Capital Protection & Emergency Circuit Breaker
Strategy Target: Short-Term Crypto Momentum Arbitrage (5m/15m markets)
Primary Directive: Prioritize absolute fund preservation; override any strategy engine instruction if safety thresholds are breached.
"""

import asyncio
import time
import logging
from typing import Optional, Dict

from agents.base import BaseAgent
from core.models import DecisionOrder
from core.message_bus import MessageBus
from database.ledger_db import LedgerDB
from config import SystemConfig, DEFAULT_CONFIG


class Agent4Shield(BaseAgent):
    def __init__(self, bus: MessageBus, db: LedgerDB, config: SystemConfig = DEFAULT_CONFIG):
        super().__init__(agent_id="agent4_shield", role="Capital Protection & Emergency Circuit Breaker", bus=bus, config=config)
        self.db = db
        
        # Risk State Tracking
        self.total_capital: float = self.config.risk.total_capital_usdc
        self.rolling_24h_loss: float = 0.0
        self.is_circuit_breaker_tripped: bool = False
        self.is_feed_stale: bool = False
        self.kill_switch_active: bool = False
        
        # Latest market spreads reported by Agent 1
        self.latest_spreads_bps: Dict[str, float] = {}

    async def start(self):
        await super().start()
        # Intercepts trade signals from Agent 2
        self.bus.subscribe("trade_signals", self.evaluate_signal_risk)
        # Subscribes to live data feed to track spreads autonomously (failing closed on missing data)
        self.bus.subscribe("data_feed", self.on_data_feed)
        # Listens for risk alerts from Agent 1 (The Eyes) and Agent 5 (The Ledger)
        self.bus.subscribe("risk_alerts", self.on_risk_alert)
        # Periodic 24h rolling loss refresh
        self._tasks.append(asyncio.create_task(self._monitor_circuit_breaker_loop()))

    async def on_data_feed(self, packet):
        """Continuously updates latest spread telemetry from Agent 1 data packets."""
        if hasattr(packet, "asset_id") and hasattr(packet, "spread_bps"):
            self.latest_spreads_bps[packet.asset_id] = packet.spread_bps

    async def on_risk_alert(self, alert: dict):
        """Processes real-time risk alerts and connectivity warnings."""
        alert_type = alert.get("type")
        
        # INSTRUCTION 2: If stale-feed warning triggers (> 2s), instantly fire emergency cancel instruction
        if alert_type == "STALE_FEED_WARNING":
            self.is_feed_stale = True
            lag = alert.get("lag_sec", 2.0)
            self.logger.critical(
                f"[STALE FEED WARNING] Feed lag {lag:.2f}s > 2.0s! Instantly triggering emergency resting order cancellation!"
            )
            await self.bus.publish("emergency_cancel", {
                "reason": f"Feed data stalled ({lag:.2f}s lag)",
                "timestamp": time.time()
            })

        elif alert_type == "STALE_FEED_RESOLVED":
            self.is_feed_stale = False
            self.logger.info("[STALE FEED RESOLVED] Connectivity restored to normal.")

        elif alert_type == "PIPELINE_LOCK":
            self.logger.critical(f"[EMERGENCY LOCK] Triggered by Ledger: {alert.get('reason')}")
            await self.trigger_kill_switch(f"Ledger reconciliation lock: {alert.get('reason')}")

    async def evaluate_signal_risk(self, order: DecisionOrder):
        """
        INSTRUCTION 1: Enforce hard-coded boundaries before any order leaves Agent 3.
        """
        # Guard 0: Kill Switch or Circuit Breaker Active
        if self.kill_switch_active:
            self.logger.error(f"[ORDER BLOCKED] Kill switch active. Order {order.signal_id} rejected.")
            return

        if self.is_circuit_breaker_tripped:
            self.logger.error(
                f"[ORDER BLOCKED] 24h Daily Loss Circuit Breaker tripped (-{self.rolling_24h_loss:.2f} USDC). "
                f"Trading halted."
            )
            return

        if self.is_feed_stale:
            self.logger.error(f"[ORDER BLOCKED] Stale feed detected. Order {order.signal_id} rejected.")
            return

        # Guard 1: Position Size Cap (Max exposure <= 2% of total capital)
        max_notional_cap = self.total_capital * (self.config.risk.max_position_exposure_pct / 100.0)
        proposed_notional = order.target_limit_price * order.max_size_shares

        if proposed_notional > max_notional_cap:
            capped_shares = max_notional_cap / order.target_limit_price
            self.logger.warning(
                f"[POSITION CAP APPLIED] Proposed ${proposed_notional:.2f} exceeds 2% cap (${max_notional_cap:.2f}). "
                f"Resizing shares from {order.max_size_shares:.2f} to {capped_shares:.2f}."
            )
            order.max_size_shares = capped_shares
            proposed_notional = max_notional_cap

        # Guard 1b: Aggregate Open Exposure & Cash Availability Guard
        acct = self.db.get_portfolio_accounting(initial_capital=self.total_capital)
        current_cash = acct["cash_balance"]
        if current_cash < proposed_notional:
            self.logger.warning(
                f"[CASH GUARD BLOCKED] Insufficient available cash (${current_cash:.2f}) "
                f"for proposed order (${proposed_notional:.2f}). Order rejected."
            )
            return

        max_concurrent_positions = 5
        max_aggregate_exposure = self.total_capital * 0.20  # 20% aggregate cap ($2,000 max)
        if acct["open_count"] >= max_concurrent_positions or (acct["open_cost"] + proposed_notional) > max_aggregate_exposure:
            self.logger.warning(
                f"[EXPOSURE GUARD BLOCKED] Cannot open new position. Current open: {acct['open_count']} positions "
                f"(${acct['open_cost']:.2f} notional). Ceiling: {max_concurrent_positions} positions or ${max_aggregate_exposure:.2f} total."
            )
            return

        # Guard 2: Spread Guard (FAIL CLOSED on missing telemetry, block if spread > ceiling)
        market_spread_bps = self.latest_spreads_bps.get(order.asset_id)
        if market_spread_bps is None:
            self.logger.warning(
                f"[SPREAD GUARD BLOCKED] No spread telemetry available for asset {order.asset_id}. "
                f"Failing closed — order {order.signal_id} rejected."
            )
            return

        if market_spread_bps > self.config.risk.max_spread_bps_shield:
            self.logger.warning(
                f"[SPREAD GUARD BLOCKED] Target market spread {market_spread_bps:.1f} bps exceeds "
                f"safety ceiling ({self.config.risk.max_spread_bps_shield} bps). Order rejected."
            )
            return

        # Passed all guardrails! Forward approved order to Agent 3 (The Hands)
        self.logger.info(
            f"[SHIELD APPROVED] Order {order.signal_id} verified. Notional: ${order.target_limit_price * order.max_size_shares:.2f} "
            f"(<= 2% cap). Dispatching to Execution Layer."
        )
        await self.bus.publish("execution_commands", order)

    async def _monitor_circuit_breaker_loop(self):
        """
        INSTRUCTION 1: Daily Loss Circuit Breaker.
        If cumulative realized/unrealized losses cross 5% within rolling 24h, halt immediately.
        """
        while self.is_running:
            await asyncio.sleep(1.0)
            now = time.time()
            cutoff_24h = now - 86400.0
            
            with self.db._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT SUM(net_pnl) as total_pnl FROM trades WHERE exit_time >= ? AND net_pnl < 0",
                    (cutoff_24h,)
                )
                row = cur.fetchone()
                loss_24h = abs(row["total_pnl"]) if row and row["total_pnl"] is not None else 0.0

            self.rolling_24h_loss = loss_24h
            loss_threshold = self.total_capital * (self.config.risk.daily_loss_circuit_breaker_pct / 100.0)

            if loss_24h >= loss_threshold:
                if not self.is_circuit_breaker_tripped:
                    self.is_circuit_breaker_tripped = True
                    self.logger.critical(
                        f"[CIRCUIT BREAKER TRIPPED] 24-Hour Loss: -${loss_24h:.2f} >= 5% Threshold (-${loss_threshold:.2f}). "
                        f"HALTING ALL TRADING ENGINES IMMEDIATELY!"
                    )
                    await self.bus.publish("emergency_cancel", {
                        "reason": f"24h loss circuit breaker tripped: -${loss_24h:.2f}",
                        "timestamp": now
                    })

    async def trigger_kill_switch(self, reason: str):
        """
        INSTRUCTION 3: Prime continuous kill-switch script to lock proxy wallet parameters
        if abnormal transaction anomalies occur.
        """
        self.kill_switch_active = True
        self.logger.critical(f"[KILL-SWITCH ENGAGED] Reason: {reason}. Locking proxy wallet & clearing pipeline!")
        await self.bus.publish("emergency_cancel", {
            "reason": f"Kill switch engaged: {reason}",
            "timestamp": time.time()
        })
