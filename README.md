# JAZZ Trading United Nation (JAZZ-UN)
### Quantitative Research & Multi-Agent Simulation for Polymarket Short-Term Crypto Markets

The **JAZZ Trading United Nation** is a quantitative research and multi-agent simulation framework designed to empirically investigate whether Polymarket Central Limit Order Book (CLOB) 5m and 15m crypto direction contracts lag external high-frequency spot momentum.

> **Phase 1 Status: READ-ONLY Research & Measurement Mode.**
> No real orders are dispatched, no private keys are loaded, and no capital is at risk. All live data probes operate exclusively in read-only observation mode. Phase 2 (execution) will only be considered if empirical data satisfies the pre-committed Go gates defined in `research/GATE.md`.

---

## 1. Empirical Research & Measurement Layer

To replace unvalidated market-lag assumptions with hard data, the repository includes a standalone measurement toolkit:

- **`research/lag_probe.py`**: Standalone probe that connects to high-frequency spot feeds with automatic regional fallback (**Bybit -> OKX -> Coinbase -> Binance** to bypass ISP blocks). When rolling 60-second velocity exceeds $\pm 0.3\%$, it logs 23 empirical fields including $t_0$, $t+1\text{s}$, $t+5\text{s}$, and $t+30\text{s}$ order book quotes, feed latency, and backfilled terminal settlement.
- **`research/fair_value.py`**: Non-circular Black-Scholes binary option digital call/put pricing engine:
  $$P(S_T \ge K) = \Phi(d_2) \quad \text{where} \quad d_2 = \frac{\ln(S/K) - \frac{1}{2}\sigma^2 T}{\sigma\sqrt{T}}$$
  Assumes $r=0$ over short expirations and estimates annualized $\sigma$ from high-frequency 60-second spot returns. **Crucially, this model evaluates only exogenous state and never consumes Polymarket prices.**
- **`research/analyze.py`**: Statistical analyzer computing post-burst ask drift distributions, quote survival rates, Brier score probability calibration, and empirical round-trip hurdle costs (~450 bps required edge).
- **`research/GATE.md`**: Pre-commitment quantitative gates (G-1 to G-4 Go criteria vs. S-1 to S-4 Immediate Shelve criteria) preventing sunk-cost bias.

---

## 2. The 5-Agent Architecture (Simulation Framework)

```
+-----------------------------------------------------------------------+
|                 JAZZ TRADING UNITED NATION PIPELINE                  |
+-----------------------------------------------------------------------+
|                                                                       |
|  [Agent 1: The Eyes]                                                  |
|  High-Frequency Ingestion & Feed Harmonizer                           |
|  * Spot feeds (BTC, ETH, SOL) + Polymarket CLOB books                 |
|  * Dynamic Filter: Expiry > 30s hard drop                             |
|  * Computes mid-price-relative spreads (bps) & 60s spot velocity      |
|  * Watchdog Timer: Alerts if feed lag > 2.0s                          |
|                                |                                      |
|                                v                                      |
|  [Agent 2: The Brain]                                                 |
|  Momentum Arbitrage Signal Evaluator                                  |
|  * Detects > 0.3% directional spot velocity in 60s window             |
|  * Bidirectional: YES tokens on upward burst, NO tokens on downward   |
|  * Computes exogenous fair probability via Black-Scholes binary model |
|  * Gating: Delta >= 3.5%, Depth > $500 USDC, Spread <= 400 bps        |
|                                |                                      |
|                                v                                      |
|  [Agent 4: The Shield]                                                |
|  Risk Management Guardrails & Circuit Breakers                        |
|  * Fail-Closed Spread Guard: Rejects if spread > 400 bps or missing   |
|  * Position Size Cap: Max 2% of total portfolio per market            |
|  * Daily Loss Circuit Breaker: Halts engine if 24h loss >= 5%         |
|  * Stale-Feed Tripwire: Emergency cancels resting orders if lag > 2s  |
|                                |                                      |
|                                v                                      |
|  [Agent 3: The Hands]                                                 |
|  Order Execution & Simulation Layer                                   |
|  * Post-only Limit Orders (strictly no market or aggressive sweeps)   |
|  * BUY side only on target outcome tokens                             |
|  * Simulated EIP-712 cryptographic signature headers                  |
|  * SQLite execution audit trail                                       |
|                                |                                      |
|                                v                                      |
|  [Agent 5: The Ledger]                                                |
|  Real-Time Position & Balance Auditor                                 |
|  * Position lifecycle and market settlement tracking                  |
|  * Performance analytics: Win Rate, Profit Factor, Latency, Drawdown  |
|  * Discrepancy Lock: Locks engine if balance drift > 0.001 USDC       |
|                                                                       |
+-----------------------------------------------------------------------+
```

---

## 3. Directory Structure

```
jazz_trading_un/
├── README.md
├── requirements.txt
├── config.py                 # System thresholds, spread limits, and risk caps
├── main.py                   # Multi-agent simulation runner
├── bot_service.py            # Background daemon bot service with SQLite IPC
├── app.py                    # Real-time Streamlit web dashboard
├── core/
│   ├── models.py             # EventPacket, DecisionOrder, ExecutionRecord, TradeRecord
│   └── message_bus.py        # Asynchronous event pub/sub bus
├── database/
│   └── ledger_db.py          # SQLite immutable audit and analytics ledger
├── agents/
│   ├── base.py               # Base agent lifecycle
│   ├── agent1_eyes.py        # Data Ingestion (The Eyes)
│   ├── agent2_brain.py       # Strategy Engine (The Brain)
│   ├── agent3_hands.py       # Execution Layer (The Hands)
│   ├── agent4_shield.py      # Risk Management (The Shield)
│   └── agent5_ledger.py      # State & Portfolio (The Ledger)
├── simulation/
│   └── mock_exchange.py      # Microstructure simulation with realistic books
├── research/
│   ├── GATE.md               # Pre-commitment go/no-go thresholds
│   ├── fair_value.py         # Black-Scholes binary option digital model
│   ├── lag_probe.py          # Multi-exchange empirical probe (Read-only)
│   ├── analyze.py            # Statistical analyzer & calibration suite
│   └── data/                 # Empirical observations (CSV & JSONL)
└── tests/
    ├── test_fair_value.py    # Analytical tests for pricing model
    └── test_jazz_un.py       # 14 unit and integration tests across 5 agents
```

---

## 4. How to Run

All commands can be copy-pasted directly:

### 1. Launch Real-Time Streamlit Trading Terminal Dashboard
```bash
streamlit run app.py
```
*(Or run via virtual environment: `.venv\Scripts\streamlit run app.py`)*

### 2. Run Automated Test Suite (100% Passing)
```bash
py -m unittest discover -s tests -p "test_*.py" -v
```

### 3. Run Live Multi-Agent Simulation
```bash
py main.py --rounds 5
```

### 4. Run Empirical Lag Probe (Test Mode)
```bash
py research/lag_probe.py --test
```

### 5. Run Statistical Analysis on Probe Data
```bash
py research/analyze.py
```

---

## 5. Audit Corrections Summary

| Item | Previous State | Revised State |
| :--- | :--- | :--- |
| **Brain Fair Value** | Circular formula ($theoretical = ask + momentum$; $ask$ cancelled out). | Exogenous Black-Scholes binary option model ($P = \Phi(d_2)$) with $r=0$. |
| **Momentum Direction** | Unidirectional (BUY YES on $+0.3\%$). Downward momentum ignored. | Bidirectional (BUY YES on $\ge +0.3\%$; BUY NO on $\le -0.3\%$). |
| **Spread Gate** | Fixed at 50 bps against \$1 denominator, choking valid trades. | Set to realistic 400 bps based on $(spread / mid\_price \times 10000)$. |
| **Shield Spread Guard** | Bypassed agent autonomy via manual assignment in `main.py`. | Autonomous `data_feed` subscription; fails closed if telemetry missing. |
| **Spot Data Access** | Hardcoded to Binance (ISP-blocked in regions like Malaysia). | Automatic fallback: Bybit $\rightarrow$ OKX $\rightarrow$ Coinbase $\rightarrow$ Binance. |
| **Execution Claims** | Claims of live on-chain trading without validation. | Formally classified as Phase 1 research probe and mock simulation framework. |
