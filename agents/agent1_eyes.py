"""
Agent 1: Data Ingestion (The Eyes)
Role: High-Frequency Data Ingestion & Feed Harmonizer
Strategy Target: Short-Term Crypto Momentum Arbitrage (5m/15m markets)
Primary Directive: Pull, normalize, and stream ultra-low-latency price feeds and order book metrics without data drift.
"""

import asyncio
import time
import json
import logging
from collections import deque
from typing import Dict, Optional, Tuple

from agents.base import BaseAgent
from core.models import EventPacket
from core.message_bus import MessageBus
from config import SystemConfig, DEFAULT_CONFIG


class Agent1Eyes(BaseAgent):
    def __init__(self, bus: MessageBus, config: SystemConfig = DEFAULT_CONFIG):
        super().__init__(agent_id="agent1_eyes", role="High-Frequency Data Ingestion & Feed Harmonizer", bus=bus, config=config)
        
        # Spot Price History: asset -> deque of (timestamp, price)
        self.spot_history: Dict[str, deque] = {
            asset: deque(maxlen=300) for asset in self.config.market.assets
        }
        self.current_spot: Dict[str, float] = {}
        
        # Order Book Cache: asset -> dict of order book metrics
        self.clob_books: Dict[str, dict] = {}
        
        # Timestamps for Watchdog
        self.last_spot_update_ts: float = time.time()
        self.last_clob_update_ts: float = time.time()
        self.stale_flag: bool = False

    async def start(self):
        await super().start()
        # Launch Watchdog Timer Loop
        self._tasks.append(asyncio.create_task(self._watchdog_loop()))

    def update_spot_price(self, asset: str, price: float, ts: Optional[float] = None):
        """
        Ingest real-time spot crypto price update (from Binance / Coinbase WebSockets).
        Maintains rolling 60s window to calculate spot_change_velocity_60s.
        """
        now = ts or time.time()
        self.last_spot_update_ts = now
        self.current_spot[asset] = price
        
        # Append to historical window
        history = self.spot_history.setdefault(asset, deque(maxlen=300))
        history.append((now, price))
        
        # Purge data older than 65s
        while history and now - history[0][0] > 65.0:
            history.popleft()

    def calculate_spot_velocity_60s(self, asset: str) -> float:
        """
        Compute spot percentage change velocity across a rolling 60-second window.
        """
        history = self.spot_history.get(asset)
        if not history or len(history) < 2:
            return 0.0
            
        current_ts, current_p = history[-1]
        target_ts = current_ts - self.config.strategy.momentum_window_sec
        
        # Find closest price at or before (now - 60s)
        base_price = history[0][1]
        for t, p in history:
            if t <= target_ts:
                base_price = p
            else:
                break
                
        if base_price <= 0:
            return 0.0
            
        velocity_pct = ((current_p - base_price) / base_price) * 100.0
        return velocity_pct

    def update_polymarket_clob(
        self,
        asset: str,
        bids: list,  # [(price, size), ...] sorted best first
        asks: list,  # [(price, size), ...] sorted best first
        secs_remaining: int,
        token_id: str,
        market_id: str = "",
        ts: Optional[float] = None
    ) -> Optional[EventPacket]:
        """
        Ingests Polymarket CLOB WebSocket L2 order book update.
        Filters markets, computes metrics, and produces EventPacket.
        """
        now = ts or time.time()
        self.last_clob_update_ts = now

        # INSTRUCTION 2: Hard drop if expiry is <= 30s to avoid orphan fills
        if secs_remaining <= self.config.market.min_secs_remaining_drop:
            self.logger.debug(f"[{asset}] Dropping market {market_id}: secs_remaining={secs_remaining} <= 30s")
            return None

        if not bids or not asks:
            return None

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid_price = (best_bid + best_ask) / 2.0
        spread = best_ask - best_bid
        spread_bps = (spread / mid_price * 10000.0) if mid_price > 0 else float("inf")

        # INSTRUCTION 3: Compute depth-within-5% and top 3 levels USDC depth
        top3_depth_usdc = sum(float(p) * float(s) for p, s in asks[:3])
        depth_within_5pct = sum(
            float(s) for p, s in asks if float(p) <= best_ask * 1.05
        ) + sum(
            float(s) for p, s in bids if float(p) >= best_bid * 0.95
        )

        spot_price = self.current_spot.get(asset, 0.0)
        spot_velocity = self.calculate_spot_velocity_60s(asset)

        # INSTRUCTION 4: Unified, timestamped JSON event packet
        packet = EventPacket(
            timestamp=now,
            asset_id=asset,
            spot_price=spot_price,
            spot_change_velocity_60s=spot_velocity,
            polymarket_best_bid=best_bid,
            polymarket_best_ask=best_ask,
            spread_bps=spread_bps,
            secs_remaining=secs_remaining,
            top3_depth_usdc=top3_depth_usdc,
            token_id=token_id,
            market_id=market_id
        )

        self.clob_books[asset] = {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid_price,
            "spread_bps": spread_bps,
            "top3_depth_usdc": top3_depth_usdc,
            "secs_remaining": secs_remaining
        }

        return packet

    async def emit_packet(self, packet: EventPacket):
        """Dispatches event packet to the internal message queue."""
        await self.bus.publish("data_feed", packet)

    async def _watchdog_loop(self):
        """
        INSTRUCTION 5: Strict watchdog timer.
        If WebSocket data stalls or lags for > 2 seconds, trigger stale-feed warning flag immediately.
        """
        while self.is_running:
            await asyncio.sleep(0.2)
            now = time.time()
            spot_lag = now - self.last_spot_update_ts
            clob_lag = now - self.last_clob_update_ts
            max_lag = max(spot_lag, clob_lag)

            if max_lag > self.config.market.watchdog_stale_threshold_sec:
                if not self.stale_flag:
                    self.stale_flag = True
                    self.logger.warning(
                        f"[WATCHDOG TRIGGERED] Data feed stalled! Lag={max_lag:.2f}s > 2.0s threshold."
                    )
                    await self.bus.publish("risk_alerts", {
                        "type": "STALE_FEED_WARNING",
                        "lag_sec": max_lag,
                        "timestamp": now,
                        "source": "Agent1Eyes"
                    })
            else:
                if self.stale_flag:
                    self.stale_flag = False
                    self.logger.info("[WATCHDOG RESOLVED] Live feed recovered.")
                    await self.bus.publish("risk_alerts", {
                        "type": "STALE_FEED_RESOLVED",
                        "timestamp": now
                    })
