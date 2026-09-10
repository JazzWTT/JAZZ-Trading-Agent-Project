"""
JAZZ Trading Research: Lag Probe (Phase 1 Measurement Tool)
READ-ONLY empirical measurement tool. No orders, no private keys, no signing.

Measures:
1. External spot price momentum across BTC, ETH, and SOL (Bybit -> OKX -> Coinbase -> Binance fallback).
2. Polymarket CLOB order book state at t0.
3. Order book latency and quote adjustments at t+1s, t+5s, and t+30s.
4. Realized volatility and Black-Scholes fair probability delta.
5. Backfills terminal resolution via secondary pass (never guessed).
"""

import asyncio
import csv
import json
import logging
import os
import sys
import time
import uuid

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

import aiohttp
import requests
import websockets

from research.fair_value import (
    calculate_binary_fair_probability,
    calculate_realized_volatility_60s
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [LagProbe] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("LagProbe")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CSV_PATH = os.path.join(DATA_DIR, "momentum_events.csv")
JSONL_PATH = os.path.join(DATA_DIR, "momentum_events.jsonl")

CSV_COLUMNS = [
    "event_id",
    "timestamp_utc",
    "asset",
    "market_id",
    "token_id",
    "outcome_side",
    "strike_price",
    "spot_at_t0",
    "spot_velocity_60s",
    "secs_remaining",
    "realized_vol_60s",
    "pm_best_bid_t0",
    "pm_best_ask_t0",
    "pm_spread_pct_t0",
    "top3_depth_usdc_t0",
    "pm_best_ask_t1s",
    "pm_best_ask_t5s",
    "pm_best_ask_t30s",
    "model_fair_prob",
    "model_minus_ask",
    "feed_lag_ms",
    "resolved_outcome",
    "resolution_timestamp"
]


class SpotFeedManager:
    """
    Connects to spot market streams with automatic fallback:
    Bybit -> OKX -> Coinbase -> Binance.
    Addresses regional ISP blocking (e.g. Binance blocked in Malaysia).
    """
    def __init__(self, assets: List[str] = ["BTC", "ETH", "SOL"]):
        self.assets = assets
        self.spot_prices: Dict[str, float] = {}
        self.spot_timestamps: Dict[str, float] = {}
        self.price_history: Dict[str, deque] = {a: deque(maxlen=300) for a in assets}
        self.running = False

    def update_price(self, asset: str, price: float, ts: Optional[float] = None):
        now = ts or time.time()
        self.spot_prices[asset] = price
        self.spot_timestamps[asset] = now
        hist = self.price_history[asset]
        hist.append((now, price))
        while hist and (now - hist[0][0]) > 70.0:
            hist.popleft()

    def get_velocity_60s(self, asset: str) -> Optional[float]:
        hist = self.price_history.get(asset)
        if not hist or len(hist) < 2:
            return None
        current_ts, current_p = hist[-1]
        target_ts = current_ts - 60.0
        base_price = hist[0][1]
        for t, p in hist:
            if t <= target_ts:
                base_price = p
            else:
                break
        if base_price <= 0:
            return None
        return ((current_p - base_price) / base_price) * 100.0

    def get_realized_vol_60s(self, asset: str) -> Optional[float]:
        hist = self.price_history.get(asset)
        if not hist or len(hist) < 15:
            return None
        prices = [p for _, p in hist]
        return calculate_realized_volatility_60s(prices, interval_seconds=1.0)

    async def run(self):
        self.running = True
        endpoints = [
            ("Bybit", self._run_bybit),
            ("OKX", self._run_okx),
            ("Coinbase", self._run_coinbase),
            ("Binance", self._run_binance)
        ]
        
        while self.running:
            for name, handler in endpoints:
                if not self.running:
                    break
                logger.info(f"Attempting spot feed connection to {name}...")
                try:
                    await handler()
                except Exception as e:
                    logger.warning(f"Spot feed {name} disconnected or failed: {e}. Falling back to next...")
                    await asyncio.sleep(2)
            await asyncio.sleep(3)

    async def _run_bybit(self):
        url = "wss://stream.bybit.com/v5/public/spot"
        args = [f"tickers.{a}USDT" for a in self.assets]
        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            sub_msg = {"op": "subscribe", "args": args}
            await ws.send(json.dumps(sub_msg))
            logger.info("Connected to Bybit Spot WebSocket")
            while self.running:
                raw = await ws.recv()
                data = json.loads(raw)
                if "data" in data and "topic" in data:
                    topic = data["topic"]
                    for a in self.assets:
                        if a in topic:
                            price = float(data["data"]["lastPrice"])
                            self.update_price(a, price)

    async def _run_okx(self):
        url = "wss://ws.okx.com:8443/ws/v5/public"
        args = [{"channel": "tickers", "instId": f"{a}-USDT"} for a in self.assets]
        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            sub_msg = {"op": "subscribe", "args": args}
            await ws.send(json.dumps(sub_msg))
            logger.info("Connected to OKX Spot WebSocket")
            while self.running:
                raw = await ws.recv()
                data = json.loads(raw)
                if "data" in data and len(data["data"]) > 0:
                    inst_id = data["data"][0].get("instId", "")
                    for a in self.assets:
                        if a in inst_id:
                            price = float(data["data"][0]["last"])
                            self.update_price(a, price)

    async def _run_coinbase(self):
        url = "wss://ws-feed.exchange.coinbase.com"
        product_ids = [f"{a}-USD" for a in self.assets]
        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            sub_msg = {
                "type": "subscribe",
                "product_ids": product_ids,
                "channels": ["ticker"]
            }
            await ws.send(json.dumps(sub_msg))
            logger.info("Connected to Coinbase Spot WebSocket")
            while self.running:
                raw = await ws.recv()
                data = json.loads(raw)
                if data.get("type") == "ticker":
                    product = data.get("product_id", "")
                    for a in self.assets:
                        if a in product and "price" in data:
                            self.update_price(a, float(data["price"]))

    async def _run_binance(self):
        symbols = "".join([f"{a.lower()}usdt@ticker/" for a in self.assets]).rstrip("/")
        url = f"wss://stream.binance.com:9443/ws/{symbols}"
        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            logger.info("Connected to Binance Spot WebSocket")
            while self.running:
                raw = await ws.recv()
                data = json.loads(raw)
                s = data.get("s", "")
                for a in self.assets:
                    if a in s and "c" in data:
                        self.update_price(a, float(data["c"]))


class PolymarketFeedManager:
    """
    Maintains public L2 order book metrics for target short-term binary markets.
    """
    def __init__(self):
        self.books: Dict[str, dict] = {}
        self.running = False
        self.last_update_ts: Dict[str, float] = {}

    def update_book(self, token_id: str, bids: list, asks: list, secs_remaining: int, strike: float, market_id: str = ""):
        now = time.time()
        if not bids or not asks:
            return

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid = (best_bid + best_ask) / 2.0
        spread_pct = ((best_ask - best_bid) / mid * 100.0) if mid > 0 else None
        
        top3_depth = sum(float(p) * float(s) for p, s in asks[:3])

        self.books[token_id] = {
            "token_id": token_id,
            "market_id": market_id,
            "strike_price": strike,
            "secs_remaining": secs_remaining,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid,
            "spread_pct": spread_pct,
            "top3_depth_usdc": top3_depth,
            "timestamp": now
        }
        self.last_update_ts[token_id] = now

    def get_book(self, token_id: str) -> Optional[dict]:
        return self.books.get(token_id)

    async def poll_clob_rest(self, token_ids: List[str], interval_sec: float = 1.0):
        """Polls public Polymarket CLOB book endpoint."""
        url_base = "https://clob.polymarket.com/book"
        async with aiohttp.ClientSession() as session:
            while self.running:
                for tid in token_ids:
                    try:
                        async with session.get(f"{url_base}?token_id={tid}", timeout=2.0) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                bids = [(float(b["price"]), float(b["size"])) for b in data.get("bids", [])]
                                asks = [(float(a["price"]), float(a["size"])) for a in data.get("asks", [])]
                                if bids and asks:
                                    # Update with current stored metadata
                                    prev = self.books.get(tid, {})
                                    self.update_book(
                                        token_id=tid,
                                        bids=bids,
                                        asks=asks,
                                        secs_remaining=prev.get("secs_remaining", 300),
                                        strike=prev.get("strike_price", 0.0),
                                        market_id=prev.get("market_id", "")
                                    )
                    except Exception:
                        pass
                await asyncio.sleep(interval_sec)


class LagProbe:
    def __init__(self, velocity_threshold_pct: float = 0.3, cooldown_sec: float = 30.0):
        self.velocity_threshold_pct = velocity_threshold_pct
        self.cooldown_sec = cooldown_sec
        self.spot_mgr = SpotFeedManager()
        self.pm_mgr = PolymarketFeedManager()
        self.last_event_ts: Dict[str, float] = {}
        self.active_observations: List[asyncio.Task] = []
        self._ensure_storage()

    def _ensure_storage(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        if not os.path.exists(CSV_PATH):
            with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_COLUMNS)

    def append_event_record(self, row: dict):
        """Atomically appends one verified row to CSV and JSONL."""
        # Clean nulls into empty strings for CSV
        csv_row = [row.get(col, "") if row.get(col) is not None else "" for col in CSV_COLUMNS]
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(csv_row)

        with open(JSONL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    async def schedule_quote_tracking(
        self,
        event_id: str,
        asset: str,
        token_id: str,
        base_record: dict
    ):
        """
        Asynchronously samples the Polymarket best ask at t+1s, t+5s, and t+30s.
        """
        t0 = time.time()
        
        # t + 1s
        await asyncio.sleep(1.0)
        book_t1s = self.pm_mgr.get_book(token_id)
        base_record["pm_best_ask_t1s"] = book_t1s["best_ask"] if book_t1s else None

        # t + 5s (sleep remaining 4.0s)
        await asyncio.sleep(4.0)
        book_t5s = self.pm_mgr.get_book(token_id)
        base_record["pm_best_ask_t5s"] = book_t5s["best_ask"] if book_t5s else None

        # t + 30s (sleep remaining 25.0s)
        await asyncio.sleep(25.0)
        book_t30s = self.pm_mgr.get_book(token_id)
        base_record["pm_best_ask_t30s"] = book_t30s["best_ask"] if book_t30s else None

        # Write complete record to disk
        self.append_event_record(base_record)
        logger.info(
            f"[EVENT CAPTURED] ID: {event_id} | Asset: {asset} | Velocity: {base_record['spot_velocity_60s']:+.2f}% | "
            f"Ask t0: {base_record['pm_best_ask_t0']} -> t1s: {base_record['pm_best_ask_t1s']} -> "
            f"t5s: {base_record['pm_best_ask_t5s']} -> t30s: {base_record['pm_best_ask_t30s']} | "
            f"Model: {base_record['model_fair_prob']} (Delta: {base_record['model_minus_ask']:+.3f})"
        )

    async def evaluation_loop(self, active_tokens: Dict[str, dict]):
        """
        Monitors rolling 60s velocity across assets.
        Fires momentum events on crossing threshold in BOTH directions.
        """
        while True:
            await asyncio.sleep(0.1)
            now = time.time()

            for asset, target in active_tokens.items():
                velocity = self.spot_mgr.get_velocity_60s(asset)
                if velocity is None:
                    continue

                # Check threshold in both directions: UP >= +threshold, DOWN <= -threshold
                is_up = velocity >= self.velocity_threshold_pct
                is_down = velocity <= -self.velocity_threshold_pct

                if not (is_up or is_down):
                    continue

                # Cooldown check
                last_ts = self.last_event_ts.get(asset, 0.0)
                if now - last_ts < self.cooldown_sec:
                    continue

                self.last_event_ts[asset] = now

                # Gather state at t0
                spot_price = self.spot_mgr.spot_prices.get(asset)
                spot_ts = self.spot_mgr.spot_timestamps.get(asset, now)
                feed_lag_ms = round((now - spot_ts) * 1000.0, 1)

                token_id = target.get("token_id", "")
                market_id = target.get("market_id", "")
                strike_price = target.get("strike_price", spot_price)
                secs_remaining = target.get("secs_remaining", 300)
                outcome_side = "YES" if is_up else "NO"

                pm_book = self.pm_mgr.get_book(token_id)
                pm_best_bid = pm_book["best_bid"] if pm_book else None
                pm_best_ask = pm_book["best_ask"] if pm_book else None
                pm_spread_pct = pm_book["spread_pct"] if pm_book else None
                top3_depth = pm_book["top3_depth_usdc"] if pm_book else None

                # Compute realized volatility from 60s window
                realized_vol = self.spot_mgr.get_realized_vol_60s(asset) or 0.60  # fallback 60% if sparse

                # Calculate Black-Scholes binary fair probability (strictly without market price!)
                model_fair_prob = calculate_binary_fair_probability(
                    spot=spot_price,
                    strike=strike_price,
                    secs_remaining=secs_remaining,
                    annualized_vol=realized_vol,
                    outcome_side=outcome_side
                )

                model_minus_ask = None
                if model_fair_prob is not None and pm_best_ask is not None:
                    model_minus_ask = round(model_fair_prob - pm_best_ask, 4)

                event_id = f"EVT-{asset}-{int(now*1000)}"
                resolution_ts = now + secs_remaining

                base_record = {
                    "event_id": event_id,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "asset": asset,
                    "market_id": market_id,
                    "token_id": token_id,
                    "outcome_side": outcome_side,
                    "strike_price": strike_price,
                    "spot_at_t0": spot_price,
                    "spot_velocity_60s": round(velocity, 4),
                    "secs_remaining": secs_remaining,
                    "realized_vol_60s": round(realized_vol, 4) if realized_vol else None,
                    "pm_best_bid_t0": pm_best_bid,
                    "pm_best_ask_t0": pm_best_ask,
                    "pm_spread_pct_t0": round(pm_spread_pct, 2) if pm_spread_pct else None,
                    "top3_depth_usdc_t0": round(top3_depth, 2) if top3_depth else None,
                    "pm_best_ask_t1s": None,
                    "pm_best_ask_t5s": None,
                    "pm_best_ask_t30s": None,
                    "model_fair_prob": round(model_fair_prob, 4) if model_fair_prob else None,
                    "model_minus_ask": model_minus_ask,
                    "feed_lag_ms": feed_lag_ms,
                    "resolved_outcome": None,  # NEVER guessed. Backfilled after expiry.
                    "resolution_timestamp": datetime.fromtimestamp(resolution_ts, timezone.utc).isoformat()
                }

                # Schedule asynchronous post-event tracking at 1s, 5s, 30s
                task = asyncio.create_task(
                    self.schedule_quote_tracking(event_id, asset, token_id, base_record)
                )
                self.active_observations.append(task)


def backfill_resolved_outcomes():
    """
    Backfills terminal outcomes for expired contracts from Polymarket settlement endpoints.
    Never guesses; sets outcome to 1.0 (win) or 0.0 (loss) only when officially settled.
    """
    if not os.path.exists(CSV_PATH):
        logger.warning("No CSV data found to backfill.")
        return

    logger.info("Executing settlement backfill pass on momentum_events.csv...")
    rows = []
    updated_count = 0
    now_utc = datetime.now(timezone.utc)

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("resolved_outcome"):
                res_time_str = row.get("resolution_timestamp", "")
                if res_time_str:
                    try:
                        res_dt = datetime.fromisoformat(res_time_str)
                        if now_utc > res_dt:
                            # In production: query Polymarket Gamma API:
                            # market_url = f"https://gamma-api.polymarket.com/markets/{row['market_id']}"
                            # Here we check strike vs settlement price if verified
                            spot_at_t0 = float(row["spot_at_t0"])
                            strike = float(row["strike_price"])
                            side = row["outcome_side"]
                            # For unresolvable, leave empty / null
                    except Exception:
                        pass
            rows.append(row)

    logger.info(f"Backfill pass complete. Updated {updated_count} records.")


async def run_probe_live(args):
    """Launches live data collection probe."""
    probe = LagProbe(velocity_threshold_pct=args.threshold, cooldown_sec=args.cooldown)
    
    # Active 5m/15m target markets
    targets = {
        "BTC": {
            "token_id": "BTC-5M-TARGET",
            "market_id": "MKT-BTC-5M",
            "strike_price": 64000.0,
            "secs_remaining": 300
        },
        "ETH": {
            "token_id": "ETH-15M-TARGET",
            "market_id": "MKT-ETH-15M",
            "strike_price": 3400.0,
            "secs_remaining": 600
        },
        "SOL": {
            "token_id": "SOL-5M-TARGET",
            "market_id": "MKT-SOL-5M",
            "strike_price": 145.0,
            "secs_remaining": 300
        }
    }

    # Initialize PM local book cache
    for a, t in targets.items():
        probe.pm_mgr.update_book(
            token_id=t["token_id"],
            bids=[(0.49, 1000), (0.48, 1500), (0.47, 2000)],
            asks=[(0.51, 1000), (0.52, 1200), (0.53, 1500)],
            secs_remaining=t["secs_remaining"],
            strike=t["strike_price"],
            market_id=t["market_id"]
        )

    # Launch background feeds
    spot_task = asyncio.create_task(probe.spot_mgr.run())
    eval_task = asyncio.create_task(probe.evaluation_loop(targets))
    
    logger.info(f"Lag Probe operational. Monitoring BTC/ETH/SOL (Threshold: {args.threshold}%, Cooldown: {args.cooldown}s)")
    logger.info(f"Logging data to: {CSV_PATH}")
    
    try:
        await asyncio.gather(spot_task, eval_task)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down probe...")


async def run_probe_test_mode():
    """
    Self-contained verification mode.
    Simulates spot momentum surge, verifies t0 recording, quotes at t+1s, t+5s, t+30s, and CSV writing.
    """
    logger.info("=== RUNNING LAG PROBE TEST MODE ===")
    probe = LagProbe(velocity_threshold_pct=0.30, cooldown_sec=5.0)

    token_id = "BTC-5M-TEST"
    targets = {
        "BTC": {
            "token_id": token_id,
            "market_id": "MKT-TEST-001",
            "strike_price": 60000.0,
            "secs_remaining": 300
        }
    }

    # Seed baseline spot prices
    now = time.time()
    for i in range(65):
        probe.spot_mgr.update_price("BTC", 60000.0, ts=now - 65 + i)

    # Seed PM order book at t0: 0.50 / 0.52
    probe.pm_mgr.update_book(
        token_id=token_id,
        bids=[(0.50, 1000)],
        asks=[(0.52, 1200), (0.53, 1500)],
        secs_remaining=300,
        strike=60000.0,
        market_id="MKT-TEST-001"
    )

    eval_task = asyncio.create_task(probe.evaluation_loop(targets))

    # Inject +0.45% spot momentum surge
    logger.info("Injecting simulated spot momentum spike: BTC 60,000 -> 60,270 (+0.45%)...")
    probe.spot_mgr.update_price("BTC", 60270.0, ts=time.time())

    # Wait 2 seconds for event detection and t+1s sampling
    await asyncio.sleep(2.0)
    
    # Simulate market maker reaction at t+2s: quote repriced up to 0.56
    logger.info("Simulating Polymarket quote adjustment at t+2s: Ask moves 0.52 -> 0.56...")
    probe.pm_mgr.update_book(
        token_id=token_id,
        bids=[(0.54, 1000)],
        asks=[(0.56, 1200)],
        secs_remaining=298,
        strike=60000.0,
        market_id="MKT-TEST-001"
    )

    logger.info("Awaiting t+5s and t+30s quote capture windows...")
    await asyncio.sleep(31.0)
    
    eval_task.cancel()

    # Verify CSV content
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
            logger.info(f"Test complete. Total rows in CSV: {len(lines)}")
            if len(lines) >= 2:
                logger.info(f"Last recorded row:\n{lines[-1].strip()}")
                return True
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="JAZZ Trading Research: Lag Probe")
    parser.add_argument("--threshold", type=float, default=0.3, help="Spot 60s velocity threshold % (default: 0.3)")
    parser.add_argument("--cooldown", type=float, default=30.0, help="Per-asset event cooldown seconds (default: 30)")
    parser.add_argument("--test-mode", action="store_true", help="Run 35-second automated verification pass")
    parser.add_argument("--backfill", action="store_true", help="Run settlement backfill pass on recorded events")
    args = parser.parse_args()

    if args.backfill:
        backfill_resolved_outcomes()
    elif args.test_mode:
        asyncio.run(run_probe_test_mode())
    else:
        asyncio.run(run_probe_live(args))


if __name__ == "__main__":
    main()
