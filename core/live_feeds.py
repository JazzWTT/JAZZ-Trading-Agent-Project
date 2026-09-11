"""
Live Data Feeds Manager
Handles real-time WebSocket connections to:
1. Coinbase & OKX WebSockets for live spot prices (BTC, ETH, SOL)
2. Polymarket CLOB WebSocket for live L2 order book data and latency telemetry
Integrates transparently with core.dns_resolver to bypass regional ISP blocking.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import requests
import websockets

from core.dns_resolver import patch_dns

logger = logging.getLogger("LiveFeeds")


# Fallback verified high-liquidity Polymarket crypto target contracts
DEFAULT_TARGET_MARKETS: Dict[str, dict] = {
    "BTC": {
        "asset": "BTC",
        "market_id": "2467206",
        "question": "Will Bitcoin reach $95,000 by December 31, 2026?",
        "strike_price": 95000.0,
        "token_id_yes": "37011650970792437921328530439273985710481032638212715110420998355785945483754",
        "token_id_no": "27201221676173593121678787264361008606480627771007041356248031697735484721466",
        "evaluation_secs_remaining": 300
    },
    "ETH": {
        "asset": "ETH",
        "market_id": "2467357",
        "question": "Will Ethereum reach $2,750 by December 31, 2026?",
        "strike_price": 2750.0,
        "token_id_yes": "109204197687767722729294908496033551963201953931111544169334789476829097062278",
        "token_id_no": "84768145019786095547717415732823502270141145470320952547313245070010555237775",
        "evaluation_secs_remaining": 300
    },
    "SOL": {
        "asset": "SOL",
        "market_id": "2467463",
        "question": "Will Solana reach $140 by December 31, 2026?",
        "strike_price": 140.0,
        "token_id_yes": "69173727652368747128236955922218906950929081188168783728953530362724870253611",
        "token_id_no": "46061353941500337945456217526255127998661855935112699202109962702794747234160",
        "evaluation_secs_remaining": 300
    }
}


def extract_strike_from_question(q: str) -> float:
    """Extracts strike price from market question string e.g. '$90,000' -> 90000.0."""
    match = re.search(r"\$([0-9,]+(?:\.[0-9]+)?)", q)
    if match:
        return float(match.group(1).replace(",", ""))
    return 0.0


from collections import deque

class LiveSpotFeedManager:
    """
    Connects to Coinbase and OKX WebSockets to stream real-time spot crypto prices
    for BTC, ETH, and SOL.
    """
    def __init__(self, on_tick: Optional[Callable[[str, float, float], None]] = None):
        self.on_tick = on_tick
        self.prices: Dict[str, float] = {
            "BTC": 77100.0,
            "ETH": 2460.0,
            "SOL": 100.0
        }
        self.last_update_ts: Dict[str, float] = {
            "BTC": time.time(),
            "ETH": time.time(),
            "SOL": time.time()
        }
        self.coinbase_history: Dict[str, deque] = {
            a: deque(maxlen=300) for a in ["BTC", "ETH", "SOL"]
        }
        self.okx_history: Dict[str, deque] = {
            a: deque(maxlen=300) for a in ["BTC", "ETH", "SOL"]
        }
        self.status: str = "INITIALIZING"
        self.running: bool = False
        self._tasks: List[asyncio.Task] = []
        self.coinbase_ws_url = "wss://ws-feed.exchange.coinbase.com"
        self.okx_ws_url = "wss://ws.okx.com:8443/ws/v5/public"

    def _calc_velocity(self, history: deque, window_sec: float = 60.0) -> float:
        """Calculates percentage change velocity over window_sec."""
        if not history or len(history) < 2:
            return 0.0
        cur_ts, cur_p = history[-1]
        target_ts = cur_ts - window_sec
        base_p = history[0][1]
        for t, p in history:
            if t <= target_ts:
                base_p = p
            else:
                break
        if base_p <= 0:
            return 0.0
        return ((cur_p - base_p) / base_p) * 100.0

    def check_cross_venue_consensus(self, asset: str, direction: str) -> bool:
        """
        QUANTITATIVE ENHANCEMENT: Validates directional momentum agreement
        between Coinbase Pro and OKX feeds to filter out single-exchange flash spikes.
        direction: 'UP' (for YES signals) or 'DOWN' (for NO signals)
        """
        cb_vel = self._calc_velocity(self.coinbase_history.get(asset, deque()))
        okx_vel = self._calc_velocity(self.okx_history.get(asset, deque()))
        
        # If one venue hasn't accumulated enough history yet, pass through safely
        if len(self.okx_history.get(asset, [])) < 2 or len(self.coinbase_history.get(asset, [])) < 2:
            return True

        if direction == "UP":
            # Both venues must support upward momentum (OKX must not be strongly negative)
            return cb_vel > 0.05 and okx_vel >= -0.05
        elif direction == "DOWN":
            # Both venues must support downward momentum (OKX must not be strongly positive)
            return cb_vel < -0.05 and okx_vel <= 0.05
        return True

    async def start(self):
        """Starts live WebSocket consumer loops."""
        patch_dns()
        self.running = True
        self._tasks.append(asyncio.create_task(self._coinbase_loop()))
        self._tasks.append(asyncio.create_task(self._okx_loop()))
        logger.info("LiveSpotFeedManager started (Coinbase & OKX streams).")

    async def stop(self):
        """Stops all feed loops."""
        self.running = False
        for t in self._tasks:
            t.cancel()
        self.status = "STOPPED"
        logger.info("LiveSpotFeedManager stopped.")

    async def _coinbase_loop(self):
        """Streams ticks from Coinbase Pro WebSocket."""
        while self.running:
            try:
                self.status = "CONNECTING"
                async with websockets.connect(
                    self.coinbase_ws_url,
                    ping_interval=20,
                    ping_timeout=10
                ) as ws:
                    sub_msg = {
                        "type": "subscribe",
                        "product_ids": ["BTC-USD", "ETH-USD", "SOL-USD"],
                        "channels": ["ticker"]
                    }
                    await ws.send(json.dumps(sub_msg))
                    self.status = "ONLINE"
                    logger.info("Connected to Coinbase WebSocket ticker feed.")

                    while self.running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if data.get("type") == "ticker":
                            prod = data.get("product_id")
                            price_str = data.get("price")
                            if prod and price_str:
                                asset = prod.split("-")[0]
                                price = float(price_str)
                                now = time.time()
                                self.prices[asset] = price
                                self.last_update_ts[asset] = now
                                self.coinbase_history[asset].append((now, price))
                                if self.on_tick:
                                    try:
                                        self.on_tick(asset, price, now)
                                    except Exception as e:
                                        logger.error(f"Error in on_tick callback: {e}")
            except (asyncio.CancelledError, KeyboardInterrupt):
                break
            except Exception as e:
                logger.warning(f"Coinbase WebSocket disconnected: {e}. Reconnecting in 3s...")
                self.status = "RECONNECTING"
                await asyncio.sleep(3.0)

    async def _okx_loop(self):
        """Backup stream from OKX public tickers WebSocket."""
        mapping = {"BTC-USDT": "BTC", "ETH-USDT": "ETH", "SOL-USDT": "SOL"}
        while self.running:
            try:
                async with websockets.connect(
                    self.okx_ws_url,
                    ping_interval=20,
                    ping_timeout=10
                ) as ws:
                    sub_msg = {
                        "op": "subscribe",
                        "args": [
                            {"channel": "tickers", "instId": "BTC-USDT"},
                            {"channel": "tickers", "instId": "ETH-USDT"},
                            {"channel": "tickers", "instId": "SOL-USDT"}
                        ]
                    }
                    await ws.send(json.dumps(sub_msg))
                    logger.info("Connected to OKX WebSocket backup ticker feed.")

                    while self.running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if "data" in data and len(data["data"]) > 0:
                            for item in data["data"]:
                                inst = item.get("instId")
                                last = item.get("last")
                                if inst in mapping and last:
                                    asset = mapping[inst]
                                    price = float(last)
                                    now = time.time()
                                    self.okx_history[asset].append((now, price))
                                    # Update if Coinbase hasn't updated for > 2s
                                    if now - self.last_update_ts.get(asset, 0) > 2.0:
                                        self.prices[asset] = price
                                        self.last_update_ts[asset] = now
                                        if self.on_tick:
                                            self.on_tick(asset, price, now)
            except (asyncio.CancelledError, KeyboardInterrupt):
                break
            except Exception as e:
                logger.debug(f"OKX WebSocket error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5.0)


class LivePolymarketFeedManager:
    """
    Manages real-time Polymarket order books via CLOB WebSocket.
    Discovers active crypto markets and streams live L2 order book metrics.
    """
    def __init__(
        self,
        on_book_update: Optional[Callable] = None
    ):
        self.on_book_update = on_book_update
        self.target_markets: Dict[str, dict] = dict(DEFAULT_TARGET_MARKETS)
        self.token_to_asset: Dict[str, Tuple[str, str]] = {}  # token_id -> (asset, outcome)
        
        # Local Order Books: token_id -> {'bids': [...], 'asks': [...], 'best_bid': float, 'best_ask': float, 'spread_bps': float, 'top3_depth': float, 'ts': float}
        self.books: Dict[str, dict] = {}
        
        self.status: str = "INITIALIZING"
        self.latency_ms: float = 35.0
        self.last_ping_ts: float = time.time()
        self.running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._roll_task: Optional[asyncio.Task] = None
        self._ws = None
        self.clob_ws_url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def discover_markets(self):
        """Fetches active crypto markets via Polymarket Gamma API."""
        patch_dns()
        try:
            url = "https://gamma-api.polymarket.com/events?limit=50&active=true&closed=false&tag_slug=crypto"
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                events = r.json()
                for e in events:
                    for m in e.get("markets", []):
                        q = m.get("question", "")
                        tokens_str = m.get("clobTokenIds")
                        if not tokens_str:
                            continue
                        tokens = json.loads(tokens_str) if isinstance(tokens_str, str) else tokens_str
                        if len(tokens) < 2:
                            continue

                        vol = float(m.get("volume24hr") or 0)
                        for asset in ["BTC", "ETH", "SOL"]:
                            name = "Bitcoin" if asset == "BTC" else ("Ethereum" if asset == "ETH" else "Solana")
                            if name in q and ("reach" in q.lower() or "dip" in q.lower()) and vol > 1000:
                                strike = extract_strike_from_question(q)
                                if strike > 0:
                                    self.target_markets[asset] = {
                                        "asset": asset,
                                        "market_id": m.get("id"),
                                        "question": q,
                                        "strike_price": strike,
                                        "token_id_yes": tokens[0],
                                        "token_id_no": tokens[1],
                                        "evaluation_secs_remaining": 300
                                    }
                                    logger.info(f"Discovered active Polymarket target for {asset}: {q}")
                                    break
        except Exception as e:
            logger.warning(f"Could not discover dynamic markets via Gamma API ({e}). Using verified fallback contracts.")

        # Re-build token_to_asset mapping
        self.token_to_asset.clear()
        for asset, mkt in self.target_markets.items():
            self.token_to_asset[mkt["token_id_yes"]] = (asset, "YES")
            self.token_to_asset[mkt["token_id_no"]] = (asset, "NO")

    async def start(self):
        """Starts market discovery and connects to Polymarket CLOB WebSocket."""
        patch_dns()
        self.discover_markets()
        self.running = True
        self._task = asyncio.create_task(self._clob_loop())
        self._roll_task = asyncio.create_task(self._auto_roll_loop())
        logger.info("LivePolymarketFeedManager started.")

    async def stop(self):
        """Stops the CLOB stream."""
        self.running = False
        if self._task:
            self._task.cancel()
        if self._roll_task:
            self._roll_task.cancel()
        self.status = "STOPPED"
        logger.info("LivePolymarketFeedManager stopped.")

    async def _auto_roll_loop(self):
        """Periodically scans Gamma API for newly listed/rolled crypto contracts."""
        while self.running:
            try:
                await asyncio.sleep(60.0)
                old_tokens = set(self.token_to_asset.keys())
                await asyncio.to_thread(self.discover_markets)
                new_tokens = set(self.token_to_asset.keys())
                added = list(new_tokens - old_tokens)
                if added and self._ws and not getattr(self._ws, "closed", True):
                    sub_msg = {"type": "market", "assets_ids": added}
                    await self._ws.send(json.dumps(sub_msg))
                    logger.info(f"Auto-rolled Polymarket subscriptions. Subscribed to {len(added)} new tokens: {added}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Error in auto-rolling contract discovery: {e}")

    async def _clob_loop(self):
        """Maintains persistent WebSocket connection to Polymarket CLOB."""
        headers = {"User-Agent": "Mozilla/5.0"}
        token_ids = list(self.token_to_asset.keys())

        while self.running:
            try:
                self.status = "CONNECTING"
                t0 = time.time()
                async with websockets.connect(
                    self.clob_ws_url,
                    additional_headers=headers,
                    ping_interval=20,
                    ping_timeout=10
                ) as ws:
                    self._ws = ws
                    self.latency_ms = round((time.time() - t0) * 1000.0, 1)
                    self.status = "ONLINE"
                    logger.info(f"Connected to Polymarket CLOB WebSocket (Latency: {self.latency_ms:.1f}ms). Subscribing to {len(token_ids)} tokens...")

                    sub_msg = {
                        "type": "market",
                        "assets_ids": token_ids
                    }
                    await ws.send(json.dumps(sub_msg))

                    while self.running:
                        msg = await ws.recv()
                        now = time.time()
                        data = json.loads(msg)

                        # Polymarket sends initial snapshot as a list of book objects
                        if isinstance(data, list):
                            for item in data:
                                self._process_clob_item(item, now)
                        elif isinstance(data, dict):
                            self._process_clob_item(data, now)

            except (asyncio.CancelledError, KeyboardInterrupt):
                break
            except Exception as e:
                logger.warning(f"Polymarket CLOB WebSocket error: {e}. Reconnecting in 3s...")
                self.status = "RECONNECTING"
                await asyncio.sleep(3.0)

    def _process_clob_item(self, item: dict, now: float):
        """Parses book snapshot or price_change updates and maintains internal state."""
        event_type = item.get("event_type")
        
        # 1. Full L2 Book Snapshot
        if event_type == "book":
            token_id = item.get("asset_id")
            if not token_id or token_id not in self.token_to_asset:
                return

            raw_bids = item.get("bids", [])
            raw_asks = item.get("asks", [])

            # Parse and sort: bids descending (highest first), asks ascending (lowest first)
            bids = sorted(
                [(float(b["price"]), float(b["size"])) for b in raw_bids if float(b.get("price", 0)) > 0],
                key=lambda x: x[0],
                reverse=True
            )
            asks = sorted(
                [(float(a["price"]), float(a["size"])) for a in raw_asks if float(a.get("price", 0)) > 0],
                key=lambda x: x[0]
            )

            if not bids or not asks:
                return

            best_bid = bids[0][0]
            best_ask = asks[0][0]
            mid_price = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid
            spread_bps = (spread / mid_price * 10000.0) if mid_price > 0 else 0.0
            top3_depth = sum(p * s for p, s in asks[:3])

            # Order Flow Imbalance (OFI) on top 5 levels: (bid_vol - ask_vol) / (bid_vol + ask_vol)
            top5_bid_vol = sum(s for p, s in bids[:5])
            top5_ask_vol = sum(s for p, s in asks[:5])
            tot_5_vol = top5_bid_vol + top5_ask_vol
            ofi = (top5_bid_vol - top5_ask_vol) / tot_5_vol if tot_5_vol > 0 else 0.0

            self.books[token_id] = {
                "bids": bids,
                "asks": asks,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid_price": mid_price,
                "spread_bps": spread_bps,
                "top3_depth": top3_depth,
                "ofi": round(ofi, 4),
                "timestamp": now
            }

            asset, outcome = self.token_to_asset[token_id]
            mkt = self.target_markets.get(asset, {})
            secs_remaining = mkt.get("evaluation_secs_remaining", 300)
            market_id = mkt.get("market_id", "")

            if self.on_book_update and outcome == "YES":
                self.on_book_update(
                    asset,
                    bids,
                    asks,
                    secs_remaining,
                    token_id,
                    market_id,
                    now,
                    round(ofi, 4)
                )

        # 2. Incremental Price Change Update
        elif event_type == "price_change":
            changes = item.get("price_changes", [])
            for ch in changes:
                token_id = ch.get("asset_id")
                if not token_id or token_id not in self.token_to_asset:
                    continue

                best_bid_str = ch.get("best_bid")
                best_ask_str = ch.get("best_ask")
                if not best_bid_str or not best_ask_str:
                    continue

                best_bid = float(best_bid_str)
                best_ask = float(best_ask_str)
                mid_price = (best_bid + best_ask) / 2.0
                spread = best_ask - best_bid
                spread_bps = (spread / mid_price * 10000.0) if mid_price > 0 else 0.0

                # Update existing book entry or synthesize
                existing = self.books.get(token_id, {})
                bids = existing.get("bids", [(best_bid, 1500.0)])
                asks = existing.get("asks", [(best_ask, 1500.0)])
                if bids:
                    bids[0] = (best_bid, bids[0][1])
                if asks:
                    asks[0] = (best_ask, asks[0][1])

                top3_depth = sum(p * s for p, s in asks[:3])

                top5_bid_vol = sum(s for p, s in bids[:5])
                top5_ask_vol = sum(s for p, s in asks[:5])
                tot_5_vol = top5_bid_vol + top5_ask_vol
                ofi = (top5_bid_vol - top5_ask_vol) / tot_5_vol if tot_5_vol > 0 else 0.0

                self.books[token_id] = {
                    "bids": bids,
                    "asks": asks,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "mid_price": mid_price,
                    "spread_bps": spread_bps,
                    "top3_depth": top3_depth,
                    "ofi": round(ofi, 4),
                    "timestamp": now
                }

                asset, outcome = self.token_to_asset[token_id]
                mkt = self.target_markets.get(asset, {})
                secs_remaining = mkt.get("evaluation_secs_remaining", 300)
                market_id = mkt.get("market_id", "")

                if self.on_book_update and outcome == "YES":
                    self.on_book_update(
                        asset,
                        bids,
                        asks,
                        secs_remaining,
                        token_id,
                        market_id,
                        now,
                        round(ofi, 4)
                    )
