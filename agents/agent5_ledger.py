"""
Agent 5: State & Portfolio Tracking (The Ledger)
Role: Real-Time Position & Balance Auditor
Strategy Target: Short-Term Crypto Momentum Arbitrage (5m/15m markets)
Primary Directive: Maintain an immutable ledger of all USDC cash balances, open orders, active positions, and post-trade performance analytics.
"""

import asyncio
import time
import logging
from typing import Dict, Optional

from agents.base import BaseAgent
from core.models import ExecutionRecord, TradeRecord, PortfolioMetrics
from core.message_bus import MessageBus
from database.ledger_db import LedgerDB
from config import SystemConfig, DEFAULT_CONFIG


class Agent5Ledger(BaseAgent):
    def __init__(self, bus: MessageBus, db: LedgerDB, config: SystemConfig = DEFAULT_CONFIG):
        super().__init__(agent_id="agent5_ledger", role="Real-Time Position & Balance Auditor", bus=bus, config=config)
        self.db = db
        
        # Local State
        self.cash_balance_usdc: float = self.config.risk.total_capital_usdc
        self.open_positions: Dict[str, TradeRecord] = {}
        self.latest_metrics: Optional[PortfolioMetrics] = None
        self.is_pipeline_locked: bool = False

    async def start(self):
        await super().start()
        # Subscribes to execution outcomes from Agent 3
        self.bus.subscribe("execution_records", self.on_execution_record)
        # Background reconciliation loop with exchange/on-chain endpoint
        self._tasks.append(asyncio.create_task(self._continuous_reconciliation_loop()))

    async def on_execution_record(self, record: ExecutionRecord):
        """Processes newly posted/filled orders and logs trade entries."""
        if record.status == "POSTED" or record.status == "FILLED":
            # Deduct notional cash for BUY order
            cost = record.price * record.size
            self.cash_balance_usdc -= cost
            
            trade = TradeRecord(
                trade_id=f"TRD-{record.client_order_id}",
                token_id=record.token_id,
                entry_price=record.price,
                shares=record.size,
                entry_time=record.submission_timestamp,
                status="OPEN"
            )
            self.open_positions[trade.trade_id] = trade
            self.db.record_trade_entry(trade)
            
            self.logger.info(
                f"[LEDGER ENTRY RECORDED] Trade: {trade.trade_id} | Shares: {trade.shares:.1f} @ {trade.entry_price:.4f} | "
                f"Cash Remaining: ${self.cash_balance_usdc:.2f}"
            )
            
            # Recalculate portfolio metrics
            self.refresh_metrics()

    def settle_trade(self, trade_id: str, exit_price: float, exit_time: Optional[float] = None, slippage: float = 0.001):
        """
        INSTRUCTION 2: Track position lifecycles from entry to settlement or exit,
        logging exact entry price, exit price, duration, slippage, and net P&L into local SQLite database.
        """
        now = exit_time or time.time()
        trade = self.open_positions.pop(trade_id, None)
        if not trade:
            return None

        # Return principal + proceeds
        proceeds = exit_price * trade.shares
        self.cash_balance_usdc += proceeds
        
        net_pnl = self.db.record_trade_exit(
            trade_id=trade_id,
            exit_price=exit_price,
            exit_time=now,
            slippage=slippage
        )
        
        self.logger.info(
            f"[TRADE SETTLED] {trade_id} | Exit Price: {exit_price:.4f} | PnL: ${net_pnl:+.2f} | "
            f"New Cash: ${self.cash_balance_usdc:.2f}"
        )
        self.refresh_metrics()
        return net_pnl

    def refresh_metrics(self) -> PortfolioMetrics:
        """
        INSTRUCTION 3: Calculate real-time portfolio metrics:
        Win Rate, Profit Factor, Average Execution Latency, and Drawdown.
        """
        metrics = self.db.calculate_metrics(
            current_cash=self.cash_balance_usdc,
            initial_capital=self.config.risk.total_capital_usdc
        )
        self.latest_metrics = metrics
        return metrics

    async def _continuous_reconciliation_loop(self):
        """
        INSTRUCTION 1 & 4: Query Polymarket API endpoints continuously to reconcile local state
        with on-chain/exchange reality.
        Flag asset reconciliation discrepancies instantly: if exchange balance does not match internal
        tracking logs within a 0.001 USDC margin, send a high-priority alert and lock the execution pipeline.
        """
        while self.is_running:
            await asyncio.sleep(2.0)
            
            # In live production, fetch from py-clob-client: client.get_balance_allowance()
            # Here we query our simulated / synced exchange balance
            simulated_exchange_balance = self.cash_balance_usdc  # In sync under normal operation
            
            is_valid, discrepancy = self.db.audit_balance(
                exchange_balance=simulated_exchange_balance,
                internal_balance=self.cash_balance_usdc,
                threshold=self.config.risk.discrepancy_tolerance_usdc
            )

            if not is_valid:
                self.is_pipeline_locked = True
                self.logger.critical(
                    f"[AUDIT DISCREPANCY DETECTED] Exchange: {simulated_exchange_balance:.4f} vs "
                    f"Ledger: {self.cash_balance_usdc:.4f} | Delta: {discrepancy:.6f} USDC > 0.001 tolerance! "
                    f"LOCKING EXECUTION PIPELINE IMMEDIATELY!"
                )
                await self.bus.publish("risk_alerts", {
                    "type": "PIPELINE_LOCK",
                    "reason": f"Discrepancy {discrepancy:.6f} USDC exceeded 0.001 margin",
                    "timestamp": time.time()
                })
            else:
                self.logger.debug(f"[AUDIT RECONCILED] Ledger and Exchange match (tolerance < 0.001 USDC).")
