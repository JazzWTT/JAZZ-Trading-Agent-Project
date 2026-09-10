"""
JAZZ Trading United Nation - Multi-Agent Engine Runner
Orchestrates all 5 agents in a live asynchronous event loop.
"""

import asyncio
import argparse
import logging
import time
import sys

from config import DEFAULT_CONFIG, SystemConfig
from core.message_bus import MessageBus
from database.ledger_db import LedgerDB
from agents.agent1_eyes import Agent1Eyes
from agents.agent2_brain import Agent2Brain
from agents.agent3_hands import Agent3Hands
from agents.agent4_shield import Agent4Shield
from agents.agent5_ledger import Agent5Ledger
from simulation.mock_exchange import MockMarketExchange


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S"
    )


async def run_simulation(rounds: int = 5):
    setup_logging()
    logger = logging.getLogger("JAZZ_UN_Orchestrator")
    logger.info("=" * 70)
    logger.info("   JAZZ TRADING UNITED NATION - LIVE MULTI-AGENT ENGINE")
    logger.info("   Strategy: Short-Term Crypto Momentum Arbitrage (5m/15m)")
    logger.info("=" * 70)

    bus = MessageBus()
    db = LedgerDB(DEFAULT_CONFIG.db_path)
    exchange = MockMarketExchange()

    # Instantiate the 5 Agents
    eyes = Agent1Eyes(bus=bus, config=DEFAULT_CONFIG)
    brain = Agent2Brain(bus=bus, config=DEFAULT_CONFIG)
    hands = Agent3Hands(bus=bus, db=db, config=DEFAULT_CONFIG)
    shield = Agent4Shield(bus=bus, db=db, config=DEFAULT_CONFIG)
    ledger = Agent5Ledger(bus=bus, db=db, config=DEFAULT_CONFIG)

    # Start agents
    await eyes.start()
    await brain.start()
    await hands.start()
    await shield.start()
    await ledger.start()

    logger.info("All 5 Agents initialized and operational:")
    logger.info("  [Agent 1 - The Eyes]   Data Ingestion & Feed Harmonizer")
    logger.info("  [Agent 2 - The Brain]  Momentum Arbitrage Signal Evaluator")
    logger.info("  [Agent 3 - The Hands]  Secure Order Execution (py-clob-client Limit Orders)")
    logger.info("  [Agent 4 - The Shield] Capital Protection & Emergency Circuit Breaker")
    logger.info("  [Agent 5 - The Ledger] Real-Time Position & Balance Auditor")
    logger.info("-" * 70)

    # Seed baseline prices across 60 seconds
    base_ts = time.time() - 65.0
    for asset in ["BTC", "ETH", "SOL"]:
        for step in range(65):
            eyes.update_spot_price(asset, exchange.spot_prices[asset], ts=base_ts + step)

    try:
        for r in range(1, rounds + 1):
            logger.info(f"\n>>> [ROUND {r}/{rounds}] Market Tick Broadcast <<<")
            
            # Simulate a momentum event on round 2 and 4
            momentum_burst = (r in [2, 4])
            spread_spike = (r == 3)  # Round 3 tests spread guard suppression

            for asset in ["BTC", "ETH"]:
                spot_price, contract = exchange.generate_tick(
                    asset=asset,
                    momentum_burst=momentum_burst,
                    spread_spike=spread_spike
                )

                # 1. Feed spot update to Agent 1
                eyes.update_spot_price(asset, spot_price)

                # 2. Feed Polymarket CLOB update to Agent 1
                packet = eyes.update_polymarket_clob(
                    asset=asset,
                    bids=contract["bids"],
                    asks=contract["asks"],
                    secs_remaining=contract["secs_remaining"],
                    token_id=contract["token_id"],
                    market_id=contract["market_id"]
                )

                if packet:
                    # Emit packet onto the bus for Agent 2 and Agent 4
                    await eyes.emit_packet(packet)

            # Allow event loop to propagate: Eyes -> Brain -> Shield -> Hands -> Ledger
            await asyncio.sleep(0.5)

            # If there are open positions, settle one to demonstrate lifecycle tracking
            if ledger.open_positions and r >= 2:
                first_trade_id = list(ledger.open_positions.keys())[0]
                trade = ledger.open_positions[first_trade_id]
                # Settle at market exit price (best bid in order book) rather than arbitrary constant
                asset_sym = trade.token_id.split("-")[0]
                current_contract = exchange.contracts.get(asset_sym, {})
                exit_price = current_contract.get("best_bid", 0.50)
                ledger.settle_trade(first_trade_id, exit_price=exit_price)

            await asyncio.sleep(0.5)

        # Print final Ledger Audit
        metrics = ledger.refresh_metrics()
        logger.info("\n" + "=" * 70)
        logger.info("   PORTFOLIO AUDIT REPORT (Agent 5 - The Ledger)")
        logger.info("=" * 70)
        logger.info(f"   USDC Cash Balance:         ${metrics.cash_balance_usdc:.2f}")
        logger.info(f"   Total Settled Trades:      {metrics.total_trades}")
        logger.info(f"   Win Rate:                  {metrics.win_rate:.1f}%")
        logger.info(f"   Profit Factor:             {metrics.profit_factor:.2f}")
        logger.info(f"   Avg Execution Latency:     {metrics.avg_execution_latency_ms:.1f} ms")
        logger.info(f"   Max Drawdown:              {metrics.max_drawdown_pct:.2f}%")
        logger.info(f"   Pipeline Status:           {'LOCKED' if metrics.is_locked else 'HEALTHY & OPERATIONAL'}")
        logger.info("=" * 70)

    finally:
        await eyes.stop()
        await brain.stop()
        await hands.stop()
        await shield.stop()
        await ledger.stop()


def main():
    parser = argparse.ArgumentParser(description="JAZZ Trading United Nation Engine")
    parser.add_argument("--rounds", type=int, default=5, help="Number of simulated market rounds")
    args = parser.parse_args()
    asyncio.run(run_simulation(rounds=args.rounds))


if __name__ == "__main__":
    main()
