"""
Agent 2: Strategy Engine (The Brain)
Role: Momentum Arbitrage Signal Evaluator
Strategy Target: Short-Term Crypto Momentum Arbitrage (5m/15m markets)
Primary Directive: Identify split-second pricing lags between external spot momentum and Polymarket probability pricing.
"""

import asyncio
import time
import uuid
import math
from typing import Optional

from agents.base import BaseAgent
from core.models import EventPacket, DecisionOrder
from core.message_bus import MessageBus
from config import SystemConfig, DEFAULT_CONFIG


class Agent2Brain(BaseAgent):
    def __init__(self, bus: MessageBus, config: SystemConfig = DEFAULT_CONFIG):
        super().__init__(agent_id="agent2_brain", role="Momentum Arbitrage Signal Evaluator", bus=bus, config=config)
        self.total_capital: float = self.config.risk.total_capital_usdc

    async def start(self):
        await super().start()
        self.bus.subscribe("data_feed", self.on_data_feed)

    async def on_data_feed(self, packet: EventPacket):
        """Processes incoming data packets from Agent 1."""
        order = self.evaluate_packet(packet)
        if order:
            self.logger.info(
                f"[SIGNAL GENERATED] {order.signal_id} | Token: {order.token_id} | "
                f"Delta: {order.delta*100:.2f}% | Edge: {order.calculated_edge_bps:.1f} bps | "
                f"Price: {order.target_limit_price:.4f} | Size: {order.max_size_shares:.1f} shares"
            )
            await self.bus.publish("trade_signals", order)

    def calculate_theoretical_probability(self, spot_velocity_60s: float, current_ask: float) -> float:
        """
        Calculate theoretical fair probability for the Polymarket "YES" token.
        Uses logistic sensitivity to external spot momentum velocity.
        """
        # Base probability anchored near current market, adjusted for directional momentum impulse
        # Sensitivity: each +0.1% spot move adds ~5% fair probability to short-duration YES contracts
        momentum_impact = (spot_velocity_60s / 0.10) * 0.05
        # Sigmoid bounded between 0.05 and 0.95
        theoretical = current_ask + momentum_impact
        return min(0.95, max(0.05, theoretical))

    def evaluate_packet(self, packet: EventPacket) -> Optional[DecisionOrder]:
        """
        Evaluates conditions for momentum arbitrage signal.
        """
        # INSTRUCTION 4: Suppress signal generation completely if spread > 50 bps
        if packet.spread_bps > self.config.strategy.max_spread_bps:
            self.logger.debug(
                f"[{packet.asset_id}] Signal suppressed: spread {packet.spread_bps:.1f} bps > 50 bps limit"
            )
            return None

        # INSTRUCTION 1: Directional momentum trigger (e.g. spot crypto moves > 0.3% within 60s)
        if packet.spot_change_velocity_60s < self.config.strategy.spot_momentum_trigger_pct:
            return None

        # INSTRUCTION 3: Market's remaining time outside the danger zone (between 2 min and 10 min left)
        if not (self.config.market.danger_zone_min_secs <= packet.secs_remaining <= self.config.market.danger_zone_max_secs):
            self.logger.debug(
                f"[{packet.asset_id}] Expiry danger zone violation: secs_remaining={packet.secs_remaining} (must be between 120s and 600s)"
            )
            return None

        # INSTRUCTION 3: Order book depth at top 3 levels exceeds $500 USDC
        if packet.top3_depth_usdc < self.config.strategy.min_depth_top3_usdc:
            self.logger.debug(
                f"[{packet.asset_id}] Insufficient liquidity: top3 depth ${packet.top3_depth_usdc:.2f} < $500 USDC"
            )
            return None

        # INSTRUCTION 1 & 2: Calculate theoretical fair probability and pricing lag delta
        theoretical_prob = self.calculate_theoretical_probability(
            packet.spot_change_velocity_60s, packet.polymarket_best_ask
        )
        delta = theoretical_prob - packet.polymarket_best_ask

        # INSTRUCTION 3: Delta >= Minimum Profit Threshold (e.g. > 3.5% = 0.035)
        min_threshold = self.config.strategy.min_profit_threshold_pct / 100.0
        if delta < min_threshold:
            return None

        # Calculate sizing: Limit to depth available and initial safe fraction
        target_limit_price = packet.polymarket_best_ask
        edge_bps = delta * 10000.0
        
        # Max size bounded by top 3 levels depth in shares
        max_size_shares = (packet.top3_depth_usdc * 0.40) / target_limit_price

        signal_id = f"SIG-{packet.asset_id}-{int(time.time()*1000)}"
        
        # INSTRUCTION 4: Output structured JSON decision order
        return DecisionOrder(
            signal_id=signal_id,
            action="BUY",
            token_id=packet.token_id or f"{packet.asset_id}-5M-YES",
            target_limit_price=target_limit_price,
            calculated_edge_bps=edge_bps,
            max_size_shares=max_size_shares,
            timestamp=time.time(),
            theoretical_probability=theoretical_prob,
            delta=delta,
            asset_id=packet.asset_id
        )
