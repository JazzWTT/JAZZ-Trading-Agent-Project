"""
Agent 3: Execution Layer (The Hands)
Role: Secure Order Execution & Transaction Dispatcher
Strategy Target: Short-Term Crypto Momentum Arbitrage (5m/15m markets)
Primary Directive: Flawlessly sign and route orders using strict safety parameters—never use market orders.
"""

import asyncio
import time
import uuid
import hashlib
import random
import logging
from typing import Optional, Dict, Any

from agents.base import BaseAgent
from core.models import DecisionOrder, ExecutionRecord
from core.message_bus import MessageBus
from database.ledger_db import LedgerDB
from config import SystemConfig, DEFAULT_CONFIG


class Agent3Hands(BaseAgent):
    def __init__(self, bus: MessageBus, db: LedgerDB, config: SystemConfig = DEFAULT_CONFIG):
        super().__init__(agent_id="agent3_hands", role="Secure Order Execution & Transaction Dispatcher", bus=bus, config=config)
        self.db = db
        self.active_orders: Dict[str, ExecutionRecord] = {}

    async def start(self):
        await super().start()
        # Listens for approved execution commands from Agent 4 (The Shield)
        self.bus.subscribe("execution_commands", self.on_execution_command)
        # Listens for emergency cancellation directives
        self.bus.subscribe("emergency_cancel", self.on_emergency_cancel)

    async def on_execution_command(self, order: DecisionOrder):
        """Processes approved decision orders."""
        await self.execute_order(order)

    async def on_emergency_cancel(self, alert: dict):
        """Cancels all open resting limit orders immediately upon risk trigger."""
        reason = alert.get("reason", "Unknown emergency")
        self.logger.warning(f"[EMERGENCY CANCEL RECEIVED] Reason: {reason}. Cancelling all open orders...")
        await self.cancel_all_orders(reason)

    def _sign_eip712_order(self, token_id: str, price: float, size: float, client_order_id: str) -> str:
        """
        Simulate EIP-712 / EIP-191 cryptographic wallet signature.
        Combines order parameters, chain domain, and salt into signature digest.
        """
        payload = f"EIP712_ORDER:token={token_id}:price={price:.4f}:size={size:.2f}:nonce={client_order_id}"
        sig = "0x" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return sig

    async def execute_order(self, order: DecisionOrder) -> Optional[ExecutionRecord]:
        """
        Executes limit order via py-clob-client protocol rules.
        Permanently disabled: strategy shelved on evidence.
        """
        raise RuntimeError("Strategy shelved. Execution permanently disabled.")

        start_ts = time.time()
        client_order_id = f"CLOB-{uuid.uuid4().hex[:12].upper()}"

        # INSTRUCTION 2: MANDATORY Limit Orders only. Never market orders or FOK sweeps.
        order_type = "LIMIT"
        
        # INSTRUCTION 2: Always target specific token ID (side=BUY on target outcome token; never sell NO)
        if order.action != "BUY":
            self.logger.error(f"[EXECUTION REJECTED] Only side=BUY on target outcome tokens is permitted. Attempted: {order.action}")
            return None

        # INSTRUCTION 3: EIP-712 cryptographic signature
        signature = self._sign_eip712_order(
            token_id=order.token_id,
            price=order.target_limit_price,
            size=order.max_size_shares,
            client_order_id=client_order_id
        )

        # INSTRUCTION 4: Exponential backoff retry logic if API rate limits (HTTP 429) occur
        max_retries = 3
        current_attempt = 0
        success = False
        last_error = None
        network_hash = ""

        while current_attempt < max_retries and not success:
            current_attempt += 1
            try:
                # Simulate CLOB dispatch latency (10ms - 40ms)
                await asyncio.sleep(random.uniform(0.010, 0.040))
                
                # Successful post
                network_hash = "0x" + hashlib.sha256(f"{client_order_id}:{signature}".encode("utf-8")).hexdigest()
                success = True

            except Exception as e:
                last_error = str(e)
                if "429" in str(e):
                    backoff_sec = (0.1 * (2 ** current_attempt)) + random.uniform(0.01, 0.05)
                    self.logger.warning(
                        f"[RATE LIMIT 429] Backing off for {backoff_sec:.3f}s (Attempt {current_attempt}/{max_retries})"
                    )
                    await asyncio.sleep(backoff_sec)
                else:
                    self.logger.error(f"[EXECUTION FAILED] Error: {e}")
                    break

        latency_ms = (time.time() - start_ts) * 1000.0

        record = ExecutionRecord(
            client_order_id=client_order_id,
            signal_id=order.signal_id,
            token_id=order.token_id,
            side="BUY",
            price=order.target_limit_price,
            size=order.max_size_shares,
            order_type=order_type,
            submission_timestamp=time.time(),
            network_hash=network_hash if success else "NONE",
            status="POSTED" if success else "REJECTED",
            attempts=current_attempt,
            latency_ms=latency_ms,
            error=last_error if not success else None
        )

        # INSTRUCTION 5: Log every execution attempt with client order ID, timestamp, and hash to local storage
        self.db.log_execution(record)
        
        if success:
            self.active_orders[client_order_id] = record
            self.logger.info(
                f"[ORDER POSTED] ClientID: {client_order_id} | Token: {record.token_id} | "
                f"Price: {record.price:.4f} | Size: {record.size:.1f} | Hash: {record.network_hash[:16]}... | "
                f"Latency: {latency_ms:.1f}ms"
            )
            # Publish execution result to Agent 5 (The Ledger)
            await self.bus.publish("execution_records", record)
        else:
            self.logger.error(f"[ORDER REJECTED] ClientID: {client_order_id} | Error: {last_error}")

        return record

    async def cancel_all_orders(self, reason: str = "Risk guardrail triggered"):
        """Emergency batch order cancellation."""
        cancelled_count = 0
        for client_id, order in list(self.active_orders.items()):
            order.status = "CANCELLED"
            order.error = f"Emergency Cancel: {reason}"
            self.db.log_execution(order)
            cancelled_count += 1
            del self.active_orders[client_id]

        self.logger.info(f"[BATCH CANCEL COMPLETED] Cancelled {cancelled_count} resting orders.")
