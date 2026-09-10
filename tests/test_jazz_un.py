"""
JAZZ Trading United Nation - Automated Unit & Integration Tests
Verifies all 5 agents against their specific directives and safety guardrails.
"""

import unittest
import asyncio
import time
import os
import uuid

from config import SystemConfig, MarketConfig, StrategyConfig, RiskConfig
from core.models import EventPacket, DecisionOrder, ExecutionRecord, TradeRecord
from core.message_bus import MessageBus
from database.ledger_db import LedgerDB
from agents.agent1_eyes import Agent1Eyes
from agents.agent2_brain import Agent2Brain
from agents.agent3_hands import Agent3Hands
from agents.agent4_shield import Agent4Shield
from agents.agent5_ledger import Agent5Ledger


class TestJazzTradingUN(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_db_path = f"test_db_{uuid.uuid4().hex[:8]}.db"
        self.config = SystemConfig(
            market=MarketConfig(),
            strategy=StrategyConfig(),
            risk=RiskConfig(total_capital_usdc=10000.0),
            db_path=self.test_db_path
        )
        self.bus = MessageBus()
        self.db = LedgerDB(db_path=self.test_db_path)

        # Initialize 5 agents
        self.eyes = Agent1Eyes(bus=self.bus, config=self.config)
        self.brain = Agent2Brain(bus=self.bus, config=self.config)
        self.hands = Agent3Hands(bus=self.bus, db=self.db, config=self.config)
        self.shield = Agent4Shield(bus=self.bus, db=self.db, config=self.config)
        self.ledger = Agent5Ledger(bus=self.bus, db=self.db, config=self.config)

    async def asyncTearDown(self):
        await self.eyes.stop()
        await self.brain.stop()
        await self.hands.stop()
        await self.shield.stop()
        await self.ledger.stop()
        
        # Give Windows a moment to release handles
        await asyncio.sleep(0.05)
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except Exception:
                pass

    # ==========================================
    # AGENT 1 (THE EYES) TESTS
    # ==========================================
    def test_agent1_expiry_hard_drop(self):
        """Directive 2: Hard drop if secs_remaining <= 30 to avoid orphan fills."""
        bids = [(0.50, 1000)]
        asks = [(0.52, 1000)]
        
        # Test contract with 25s remaining -> must return None (dropped)
        packet = self.eyes.update_polymarket_clob(
            asset="BTC",
            bids=bids,
            asks=asks,
            secs_remaining=25,
            token_id="BTC-YES",
            market_id="MKT-1"
        )
        self.assertIsNone(packet, "Agent 1 should hard drop contracts with <= 30s remaining")

        # Test contract with 35s remaining -> accepted
        packet_valid = self.eyes.update_polymarket_clob(
            asset="BTC",
            bids=bids,
            asks=asks,
            secs_remaining=35,
            token_id="BTC-YES",
            market_id="MKT-1"
        )
        self.assertIsNotNone(packet_valid, "Agent 1 should accept contracts with > 30s remaining")

    def test_agent1_rolling_metrics_and_packet_format(self):
        """Directive 3 & 4: Rolling metrics & unified JSON event packet format."""
        now = time.time()
        # Seed 60s history
        self.eyes.update_spot_price("BTC", 60000.0, ts=now - 60)
        self.eyes.update_spot_price("BTC", 60300.0, ts=now)  # +0.50% move

        bids = [(0.50, 1000), (0.49, 1500), (0.48, 2000)]
        asks = [(0.52, 1000), (0.53, 1200), (0.54, 1500)]
        
        packet = self.eyes.update_polymarket_clob(
            asset="BTC",
            bids=bids,
            asks=asks,
            secs_remaining=300,
            token_id="BTC-YES",
            ts=now
        )
        self.assertIsNotNone(packet)
        self.assertAlmostEqual(packet.spot_change_velocity_60s, 0.50, places=2)
        self.assertEqual(packet.polymarket_best_bid, 0.50)
        self.assertEqual(packet.polymarket_best_ask, 0.52)
        self.assertAlmostEqual(packet.spread_bps, 392.2, places=1)

        # Verify output JSON packet structure: [timestamp, asset_id, spot_price, spot_change_velocity_60s, polymarket_best_bid, polymarket_best_ask, spread_bps]
        plist = packet.to_packet_list()
        self.assertEqual(len(plist), 7)
        self.assertEqual(plist[1], "BTC")
        self.assertEqual(plist[2], 60300.0)

    async def test_agent1_watchdog_timer(self):
        """Directive 5: Watchdog triggers stale-feed warning if lag > 2.0s."""
        await self.eyes.start()
        received_alerts = []
        self.bus.subscribe("risk_alerts", lambda a: received_alerts.append(a))

        # Simulate lag > 2.0s
        self.eyes.last_spot_update_ts = time.time() - 2.5
        self.eyes.last_clob_update_ts = time.time() - 2.5
        
        # Allow watchdog loop to run one iteration
        await asyncio.sleep(0.3)

        self.assertTrue(any(a.get("type") == "STALE_FEED_WARNING" for a in received_alerts))

    # ==========================================
    # AGENT 2 (THE BRAIN) TESTS
    # ==========================================
    def test_agent2_pricing_lag_and_signal_thresholds(self):
        """Directive 1, 2, 3: Delta calculation, gating conditions, and bidirectional signals."""
        # 1. Normal Valid Arbitrage Opportunity (Upward Momentum -> YES)
        valid_packet = EventPacket(
            timestamp=time.time(),
            asset_id="BTC",
            spot_price=65000.0,
            spot_change_velocity_60s=0.45,  # > 0.3% trigger
            polymarket_best_bid=0.50,
            polymarket_best_ask=0.51,
            spread_bps=198.0,              # <= 400 bps limit
            secs_remaining=300,            # 120s <= 300s <= 600s
            top3_depth_usdc=1500.0,        # > $500 USDC
            token_id="BTC-5M-YES"
        )
        order = self.brain.evaluate_packet(valid_packet)
        self.assertIsNotNone(order, "Valid upward packet should generate decision order")
        self.assertEqual(order.action, "BUY")
        self.assertEqual(order.token_id, "BTC-5M-YES")
        self.assertTrue(order.delta >= 0.035, f"Delta {order.delta} must be >= 3.5%")

        # 2. Downward Momentum -> NO Token Decision Order
        downward_packet = EventPacket(
            timestamp=time.time(),
            asset_id="BTC",
            spot_price=65000.0,
            spot_change_velocity_60s=-0.45,  # <= -0.3% trigger
            polymarket_best_bid=0.50,
            polymarket_best_ask=0.51,
            spread_bps=198.0,
            secs_remaining=300,
            top3_depth_usdc=1500.0,
            token_id="BTC-5M-YES"
        )
        down_order = self.brain.evaluate_packet(downward_packet)
        self.assertIsNotNone(down_order, "Downward momentum burst should generate decision order")
        self.assertEqual(down_order.action, "BUY")
        self.assertEqual(down_order.token_id, "BTC-5M-NO")
        self.assertTrue(down_order.delta >= 0.035, f"Delta {down_order.delta} must be >= 3.5%")

        # 3. Rejection: Spread > 400 bps
        wide_spread_packet = EventPacket(
            timestamp=time.time(),
            asset_id="BTC",
            spot_price=65000.0,
            spot_change_velocity_60s=0.50,
            polymarket_best_bid=0.45,
            polymarket_best_ask=0.55,
            spread_bps=2000.0,             # > 400 bps!
            secs_remaining=300,
            top3_depth_usdc=1500.0,
            token_id="BTC-5M-YES"
        )
        self.assertIsNone(self.brain.evaluate_packet(wide_spread_packet), "Should suppress if spread > 400 bps")

        # 4. Rejection: Expiry in Danger Zone (< 2 min)
        danger_zone_packet = EventPacket(
            timestamp=time.time(),
            asset_id="BTC",
            spot_price=65000.0,
            spot_change_velocity_60s=0.50,
            polymarket_best_bid=0.50,
            polymarket_best_ask=0.51,
            spread_bps=198.0,
            secs_remaining=90,             # 90s < 120s (2 min)
            top3_depth_usdc=1500.0,
            token_id="BTC-5M-YES"
        )
        self.assertIsNone(self.brain.evaluate_packet(danger_zone_packet), "Should reject if < 2 mins to expiry")

        # 5. Rejection: Insufficient Liquidity (< $500 USDC)
        low_liq_packet = EventPacket(
            timestamp=time.time(),
            asset_id="BTC",
            spot_price=65000.0,
            spot_change_velocity_60s=0.50,
            polymarket_best_bid=0.50,
            polymarket_best_ask=0.51,
            spread_bps=198.0,
            secs_remaining=300,
            top3_depth_usdc=350.0,         # $350 < $500
            token_id="BTC-5M-YES"
        )
        self.assertIsNone(self.brain.evaluate_packet(low_liq_packet), "Should reject if depth < $500 USDC")

    # ==========================================
    # AGENT 3 (THE HANDS) TESTS
    # ==========================================
    async def test_agent3_limit_order_enforcement_and_signing(self):
        """Directive 2, 3, 5: Limit Orders only, BUY only, EIP-712 signature, execution logging."""
        await self.hands.start()

        # Valid BUY limit order
        valid_order = DecisionOrder(
            signal_id="SIG-001",
            action="BUY",
            token_id="BTC-5M-YES",
            target_limit_price=0.52,
            calculated_edge_bps=450.0,
            max_size_shares=200.0
        )
        record = await self.hands.execute_order(valid_order)
        self.assertIsNotNone(record)
        self.assertEqual(record.order_type, "LIMIT")
        self.assertEqual(record.side, "BUY")
        self.assertTrue(record.network_hash.startswith("0x"))
        self.assertEqual(record.status, "POSTED")

        # Verify DB audit trail
        with self.db._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM executions WHERE client_order_id = ?", (record.client_order_id,))
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["side"], "BUY")

        # Invalid SELL order (attempting to sell NO)
        invalid_sell_order = DecisionOrder(
            signal_id="SIG-002",
            action="SELL",
            token_id="BTC-5M-NO",
            target_limit_price=0.48,
            calculated_edge_bps=400.0,
            max_size_shares=100.0
        )
        rejected_record = await self.hands.execute_order(invalid_sell_order)
        self.assertIsNone(rejected_record, "Should reject non-BUY orders")

    # ==========================================
    # AGENT 4 (THE SHIELD) TESTS
    # ==========================================
    async def test_agent4_position_cap_and_circuit_breaker(self):
        """Directive 1: 2% position size cap, spread guard (fail closed), and 5% daily loss breaker."""
        await self.shield.start()
        
        # Test 1: Fail Closed on missing spread telemetry
        approved_commands = []
        self.bus.subscribe("execution_commands", lambda o: approved_commands.append(o))

        missing_telemetry_order = DecisionOrder(
            signal_id="SIG-NO-SPREAD",
            action="BUY",
            token_id="ETH-15M-YES",
            asset_id="ETH",
            target_limit_price=0.50,
            calculated_edge_bps=400.0,
            max_size_shares=100.0
        )
        await self.shield.evaluate_signal_risk(missing_telemetry_order)
        self.assertEqual(len(approved_commands), 0, "Must fail closed if spread telemetry is missing")

        # Test 2: Reject if spread exceeds ceiling (e.g. 500 bps > 400 bps)
        self.shield.latest_spreads_bps["ETH"] = 500.0
        await self.shield.evaluate_signal_risk(missing_telemetry_order)
        self.assertEqual(len(approved_commands), 0, "Must reject if spread > 400 bps")

        # Test 3: Position Size Cap (2% of $10,000 = $200) with healthy spread
        self.shield.latest_spreads_bps["ETH"] = 200.0
        oversized_order = DecisionOrder(
            signal_id="SIG-CAP",
            action="BUY",
            token_id="ETH-15M-YES",
            asset_id="ETH",
            target_limit_price=0.50,
            calculated_edge_bps=400.0,
            max_size_shares=1000.0  # $500
        )
        
        await self.shield.evaluate_signal_risk(oversized_order)
        self.assertEqual(len(approved_commands), 1)
        approved = approved_commands[0]
        # Size should have been capped to $200 / 0.50 = 400 shares
        self.assertAlmostEqual(approved.max_size_shares, 400.0, places=1)
        self.assertAlmostEqual(approved.target_limit_price * approved.max_size_shares, 200.0, places=1)

        # Test 4: Daily Loss Circuit Breaker (5% of $10,000 = $500 loss)
        # Insert a simulated settled loss of -$550 in SQLite
        trade = TradeRecord(
            trade_id="TRD-LOSS",
            token_id="ETH-15M-YES",
            entry_price=0.60,
            exit_price=0.05,
            shares=1000.0,
            entry_time=time.time() - 3600,
            exit_time=time.time() - 1800,
            duration_sec=1800,
            slippage=0.001,
            net_pnl=-550.0,
            status="SETTLED"
        )
        self.db.record_trade_entry(trade)

        # Trigger monitor check
        await asyncio.sleep(1.2)
        self.assertTrue(self.shield.is_circuit_breaker_tripped, "Circuit breaker must trip when 24h loss >= 5%")

        # New orders should now be blocked
        approved_commands.clear()
        self.shield.latest_spreads_bps["BTC"] = 200.0
        new_order = DecisionOrder(
            signal_id="SIG-BLOCKED",
            action="BUY",
            token_id="BTC-5M-YES",
            asset_id="BTC",
            target_limit_price=0.50,
            calculated_edge_bps=400.0,
            max_size_shares=100.0
        )
        await self.shield.evaluate_signal_risk(new_order)
        self.assertEqual(len(approved_commands), 0, "No orders should pass after circuit breaker trips")

    # ==========================================
    # AGENT 5 (THE LEDGER) TESTS
    # ==========================================
    def test_agent5_trade_lifecycle_and_metrics(self):
        """Directive 2 & 3: Position lifecycle, SQLite DB, Win Rate, Profit Factor, Latency."""
        # 1. Open Trade
        t1 = TradeRecord(
            trade_id="TRD-WIN",
            token_id="BTC-5M-YES",
            entry_price=0.50,
            shares=200.0,
            entry_time=time.time() - 120,
            status="OPEN"
        )
        self.ledger.open_positions[t1.trade_id] = t1
        self.db.record_trade_entry(t1)

        # 2. Settle Win: exit at $0.70 (+ $40 gross, minus slippage)
        pnl_win = self.ledger.settle_trade("TRD-WIN", exit_price=0.70)
        self.assertAlmostEqual(pnl_win, 39.80, places=1)

        # 3. Add Loss Trade: exit at $0.40 (- $20)
        t2 = TradeRecord(
            trade_id="TRD-LOSS",
            token_id="SOL-5M-YES",
            entry_price=0.50,
            shares=200.0,
            entry_time=time.time() - 100,
            status="OPEN"
        )
        self.ledger.open_positions[t2.trade_id] = t2
        self.db.record_trade_entry(t2)
        pnl_loss = self.ledger.settle_trade("TRD-LOSS", exit_price=0.40)
        self.assertAlmostEqual(pnl_loss, -20.20, places=1)

        # 4. Check Portfolio Metrics
        metrics = self.ledger.refresh_metrics()
        self.assertEqual(metrics.total_trades, 2)
        self.assertEqual(metrics.win_rate, 50.0)
        self.assertTrue(metrics.profit_factor > 1.0)

    def test_agent5_balance_discrepancy_lock(self):
        """Directive 4: Instant alert & lock if balance discrepancy > 0.001 USDC."""
        # Discrepancy of 0.0005 (within 0.001) -> valid
        is_reconciled, delta = self.db.audit_balance(
            exchange_balance=10000.0005,
            internal_balance=10000.0,
            threshold=0.001
        )
        self.assertTrue(is_reconciled)

        # Discrepancy of 0.0050 (> 0.001) -> invalid, must flag
        is_reconciled, delta = self.db.audit_balance(
            exchange_balance=10000.0050,
            internal_balance=10000.0,
            threshold=0.001
        )
        self.assertFalse(is_reconciled)
        self.assertAlmostEqual(delta, 0.005, places=3)

    # ==========================================
    # INTEGRATION: END-TO-END PIPELINE TEST
    # ==========================================
    async def test_end_to_end_pipeline(self):
        """Integration: Eyes -> Brain -> Shield -> Hands -> Ledger full async pipeline."""
        await self.eyes.start()
        await self.brain.start()
        await self.shield.start()
        await self.hands.start()
        await self.ledger.start()

        now = time.time()
        # Seed 60s spot price history
        self.eyes.update_spot_price("BTC", 64000.0, ts=now - 60.0)
        self.eyes.update_spot_price("BTC", 64300.0, ts=now)  # +0.47% velocity

        # Polymarket book update (spread ~198 bps < 400 bps ceiling, depth $510 > $500)
        packet = self.eyes.update_polymarket_clob(
            asset="BTC",
            bids=[(0.50, 1000)],
            asks=[(0.51, 1000)],
            secs_remaining=300,
            token_id="BTC-5M-YES",
            market_id="MKT-BTC-5M",
            ts=now
        )
        self.assertIsNotNone(packet)

        # Publish packet to message bus
        await self.eyes.emit_packet(packet)

        # Allow event loop propagation through all 5 agents
        await asyncio.sleep(0.4)

        # 1. Verify Hands posted execution record to DB
        with self.db._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM executions WHERE token_id = ?", ("BTC-5M-YES",))
            row = cur.fetchone()
            self.assertIsNotNone(row, "Hands must post execution record to database")
            self.assertEqual(row["side"], "BUY")
            self.assertEqual(row["status"], "POSTED")

        # 2. Verify Ledger tracked position
        self.assertEqual(len(self.ledger.open_positions), 1, "Ledger must track opened position")
        trade_id = list(self.ledger.open_positions.keys())[0]
        trade = self.ledger.open_positions[trade_id]
        self.assertEqual(trade.token_id, "BTC-5M-YES")

        # 3. Verify settlement lifecycle
        pnl = self.ledger.settle_trade(trade_id, exit_price=0.55)
        self.assertGreater(pnl, 0.0)
        self.assertEqual(len(self.ledger.open_positions), 0)


if __name__ == "__main__":
    unittest.main()
