# JAZZ Trading United Nation (JAZZ-UN)
### Short-Term Crypto Momentum Arbitrage (5m/15m Expiry Markets)

The **JAZZ Trading United Nation** is a 5-agent quantitative trading team designed to exploit split-second pricing discrepancies between real-time spot crypto momentum (Binance/Coinbase) and Polymarket Central Limit Order Book (CLOB) probability markets.

---

## The 5 Team Agents

```
+-----------------------------------------------------------------------+
|                 JAZZ TRADING UNITED NATION PIPELINE                  |
+-----------------------------------------------------------------------+
|                                                                       |
|  [Agent 1: The Eyes]                                                  |
|  High-Frequency Ingestion & Feed Harmonizer                           |
|  * Real-time Spot Crypto (BTC, ETH, SOL) + Polymarket CLOB WS         |
|  * Dynamic Filter: Expiry > 30s                                      |
|  * Rolling 60s Velocity, Spreads, Top 3 Depth                         |
|  * Watchdog Timer: Alerts if feed lag > 2.0s                          |
|                                |                                      |
|                                v                                      |
|  [Agent 2: The Brain]                                                 |
|  Momentum Arbitrage Signal Evaluator                                  |
|  * Detects > 0.3% Spot Velocity Spikes in 60s                         |
|  * Computes Delta = Theoretical_Probability - Polymarket_Ask          |
|  * Enforces: Delta >= 3.5%, Depth > $500 USDC, 2m-10m Danger Zone     |
|  * Suppresses signal if Spread > 50 bps                               |
|                                |                                      |
|                                v                                      |
|  [Agent 4: The Shield]                                                |
|  Risk Management Guardrails & Circuit Breakers                        |
|  * Position Size Cap: Max 2% total capital per market                 |
|  * Daily Loss Circuit Breaker: Halts engine if 24h loss >= 5%         |
|  * Spread Guard: Rejects if spread > 50 bps                           |
|  * Stale-Feed Tripwire: Emergency cancel all resting orders (> 2s)     |
|                                |                                      |
|                                v                                      |
|  [Agent 3: The Hands]                                                 |
|  Secure Order Execution & Transaction Dispatcher                      |
|  * py-clob-client Limit Orders ONLY (Never Market/FOK sweeps)         |
|  * Side: BUY on target outcome token only                             |
|  * Cryptographic EIP-712/EIP-191 signatures                           |
|  * Exponential backoff retry on HTTP 429 rate limits                  |
|  * Audit hash logging to SQLite                                       |
|                                |                                      |
|                                v                                      |
|  [Agent 5: The Ledger]                                                |
|  Real-Time Position & Balance Auditor                                 |
|  * Continuous API / On-Chain balance reconciliation                   |
|  * SQLite database logging: Entry/Exit price, duration, slippage, PnL |
|  * Real-time metrics: Win Rate, Profit Factor, Latency, Drawdown      |
|  * Discrepancy Lock: Pipeline locked if balance drift > 0.001 USDC    |
|                                                                       |
+-----------------------------------------------------------------------+
```

---

## Directory Structure

```
jazz_trading_un/
├── README.md
├── requirements.txt
├── config.py                 # Risk limits, timeouts, and thresholds
├── main.py                   # Multi-agent simulation & live runner
├── core/
│   ├── __init__.py
│   ├── models.py             # EventPacket, DecisionOrder, ExecutionRecord
│   └── message_bus.py        # Asynchronous event bus
├── database/
│   ├── __init__.py
│   └── ledger_db.py          # SQLite immutable audit & analytics
├── agents/
│   ├── __init__.py
│   ├── base.py               # Base agent lifecycle
│   ├── agent1_eyes.py        # Data Ingestion (The Eyes)
│   ├── agent2_brain.py       # Strategy Engine (The Brain)
│   ├── agent3_hands.py       # Execution Layer (The Hands)
│   ├── agent4_shield.py      # Risk Management (The Shield)
│   └── agent5_ledger.py      # State & Portfolio (The Ledger)
├── simulation/
│   ├── __init__.py
│   └── mock_exchange.py      # Simulated ticks and order books
└── tests/
    ├── __init__.py
    └── test_jazz_un.py       # Comprehensive unit test suite
```

---

## Running the System

### 1. Run Automated Test Suite
```bash
py -m unittest discover -s tests -p "test_*.py"
```

### 2. Run Live Multi-Agent Simulation
```bash
py main.py --rounds 5
```
