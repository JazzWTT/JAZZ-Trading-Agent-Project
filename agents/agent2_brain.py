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
from research.fair_value import (
    calculate_binary_fair_probability,
    calculate_realized_volatility_60s
)


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

    def calculate_theoretical_probability(
        self,
        spot: float,
        strike: float,
        secs_remaining: float,
        annualized_vol: float = 0.60,
        outcome_side: str = "YES"
    ) -> float:
        """
        Calculate theoretical fair probability for binary option payoff.
        Uses Black-Scholes binary model: P(S_T >= K) = Phi(d2) with r=0.
        Strictly decoupled from Polymarket order book prices.
        """
        prob = calculate_binary_fair_probability(
            spot=spot,
            strike=strike,
            secs_remaining=secs_remaining,
            annualized_vol=annualized_vol,
            outcome_side=outcome_side
        )
        if prob is None:
            return 0.50
        return min(0.99, max(0.01, prob))

    def evaluate_packet(self, packet: EventPacket) -> Optional[DecisionOrder]:
        """
        Evaluates conditions for momentum arbitrage signal across both directions (YES/NO).
        """
        # INSTRUCTION 4: Suppress signal generation completely if spread > max_spread_bps limit
        if packet.spread_bps > self.config.strategy.max_spread_bps:
            self.logger.debug(
                f"[{packet.asset_id}] Signal suppressed: spread {packet.spread_bps:.1f} bps > {self.config.strategy.max_spread_bps} bps limit"
            )
            return None

        # INSTRUCTION 1: Directional momentum trigger in either direction (+/- trigger_pct)
        trigger = self.config.strategy.spot_momentum_trigger_pct
        vel = packet.spot_change_velocity_60s

        if vel >= trigger:
            outcome_side = "YES"
            target_token = packet.token_id or f"{packet.asset_id}-5M-YES"
            target_limit_price = packet.polymarket_best_ask
        elif vel <= -trigger:
            outcome_side = "NO"
            target_token = (
                packet.token_id.replace("YES", "NO")
                if packet.token_id and "YES" in packet.token_id
                else f"{packet.asset_id}-5M-NO"
            )
            target_limit_price = (
                round(1.0 - packet.polymarket_best_bid, 4)
                if packet.polymarket_best_bid > 0
                else packet.polymarket_best_ask
            )
        else:
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

        # Determine strike price: use explicit strike if present, else infer pre-momentum anchor
        strike = getattr(packet, "strike_price", 0.0)
        if strike <= 0.0:
            if vel != -100.0:
                strike = packet.spot_price / (1.0 + vel / 100.0)
            else:
                strike = packet.spot_price

        vol = getattr(packet, "realized_vol_60s", None) or 0.60

        # Calculate theoretical fair probability (exogenous state only, zero Polymarket price feedback)
        theoretical_prob = self.calculate_theoretical_probability(
            spot=packet.spot_price,
            strike=strike,
            secs_remaining=float(packet.secs_remaining),
            annualized_vol=vol,
            outcome_side=outcome_side
        )
        delta = theoretical_prob - target_limit_price

        # INSTRUCTION 3: Delta >= Minimum Profit Threshold (e.g. > 3.5% = 0.035)
        min_threshold = self.config.strategy.min_profit_threshold_pct / 100.0
        if delta < min_threshold:
            self.logger.debug(
                f"[{packet.asset_id}] Discrepancy delta {delta*100:.2f}% < {min_threshold*100:.2f}% min threshold"
            )
            return None

        # Calculate sizing: Limit to depth available and initial safe fraction
        edge_bps = delta * 10000.0
        
        # Max size bounded by top 3 levels depth in shares
        max_size_shares = (packet.top3_depth_usdc * 0.40) / target_limit_price

        signal_id = f"SIG-{packet.asset_id}-{outcome_side}-{int(time.time()*1000)}"
        
        # Output structured JSON decision order
        return DecisionOrder(
            signal_id=signal_id,
            action="BUY",
            token_id=target_token,
            target_limit_price=target_limit_price,
            calculated_edge_bps=edge_bps,
            max_size_shares=max_size_shares,
            timestamp=time.time(),
            theoretical_probability=theoretical_prob,
            delta=delta,
            asset_id=packet.asset_id
        )
