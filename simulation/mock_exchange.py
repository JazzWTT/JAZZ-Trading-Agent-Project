"""
JAZZ Trading United Nation - Mock Market Simulation
Simulates Binance/Coinbase Spot Crypto Feeds and Polymarket CLOB Order Books.
"""

import time
import random
from typing import Dict, List, Tuple
from core.models import EventPacket


class MockMarketExchange:
    def __init__(self):
        # Base spot prices
        self.spot_prices = {
            "BTC": 64250.0,
            "ETH": 3480.0,
            "SOL": 145.0
        }
        # Active contracts with expiry seconds remaining
        self.contracts = {
            "BTC": {
                "token_id": "BTC-5M-20260907-YES",
                "market_id": "MKT-BTC-5M",
                "secs_remaining": 320,  # Safely between 120s and 600s
                "best_bid": 0.50,
                "best_ask": 0.51,
                "bids": [(0.50, 1200), (0.49, 1500), (0.48, 2000)],
                "asks": [(0.51, 1100), (0.52, 1400), (0.53, 1800)]
            },
            "ETH": {
                "token_id": "ETH-15M-20260907-YES",
                "market_id": "MKT-ETH-15M",
                "secs_remaining": 540,
                "best_bid": 0.49,
                "best_ask": 0.50,
                "bids": [(0.49, 800), (0.48, 1200), (0.47, 1600)],
                "asks": [(0.50, 900), (0.51, 1300), (0.52, 1700)]
            },
            "SOL": {
                "token_id": "SOL-5M-20260907-YES",
                "market_id": "MKT-SOL-5M",
                "secs_remaining": 210,
                "best_bid": 0.50,
                "best_ask": 0.51,
                "bids": [(0.50, 1000), (0.49, 1100), (0.48, 1300)],
                "asks": [(0.51, 950), (0.52, 1200), (0.53, 1500)]
            }
        }

    def generate_tick(self, asset: str, momentum_burst: bool = False, spread_spike: bool = False, low_liquidity: bool = False, near_expiry: bool = False) -> Tuple[float, dict]:
        """
        Generates spot tick and corresponding CLOB order book state.
        """
        # 1. Update spot price
        if momentum_burst:
            # +0.45% sharp upward momentum burst within 60s window
            self.spot_prices[asset] *= 1.0045
        else:
            # Standard micro-fluctuation
            self.spot_prices[asset] *= (1.0 + random.uniform(-0.0002, 0.0002))

        spot = self.spot_prices[asset]
        contract = self.contracts[asset]

        # 2. Expiry progression
        if near_expiry:
            contract["secs_remaining"] = 25  # <= 30s trigger drop
        else:
            contract["secs_remaining"] = max(130, contract["secs_remaining"] - 1)

        # 3. Spread / depth manipulation
        if spread_spike:
            # Spread widens past 400 bps ceiling (1000 bps spread = 0.45 / 0.55)
            contract["best_bid"] = 0.45
            contract["best_ask"] = 0.55  # ~2000 bps spread
            contract["bids"] = [(0.45, 1000), (0.44, 1200), (0.43, 1500)]
            contract["asks"] = [(0.55, 1000), (0.56, 1200), (0.57, 1500)]
        elif low_liquidity:
            # Depleted depth (< $500 USDC)
            contract["asks"] = [(0.51, 100), (0.52, 150), (0.53, 200)]  # total ~$235 USDC
        else:
            # Healthy books (~198 bps spread < 400 bps ceiling)
            contract["best_bid"] = 0.50
            contract["best_ask"] = 0.51  # ~198 bps
            contract["asks"] = [(0.51, 1000), (0.52, 1200), (0.53, 1500)]
            contract["bids"] = [(0.50, 1000), (0.49, 1200), (0.48, 1500)]

        return spot, contract
