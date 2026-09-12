# POSTMORTEM: Polymarket Short-Term Crypto Momentum Arbitrage (JAZZ-UN)

**Status:** SHELVED — Strategy permanently retired on evidence (2026-09-13).  
**Capital Deployed:** $0.00.  
**Capital Lost:** $0.00.  
**Live Orders Executed:** 0.  

---

## 1. Strategy Overview and Initial Plausibility

The JAZZ-UN strategy was designed to exploit high-frequency cross-venue latency between spot cryptocurrency exchanges (Binance, Bybit, OKX, HTX, Coinbase) and Polymarket's Central Limit Order Book (CLOB) binary prediction markets.

### The Core Hypothesis
The strategy posited that when a sharp, sudden price burst occurs in underlying crypto assets (BTC, ETH, SOL) exceeding +/-0.3% in 60 seconds on centralized spot exchanges, market makers on Polymarket would lag in updating resting limit quotes. Because Polymarket contracts settle strictly binary (0 or 1 USDC based on terminal spot price relative to strike), a rapid spot move should immediately reprice the fair probability of expiring in-the-money (ITM). If resting asks on Polymarket remained unchanged for 1–5 seconds following a spot move, a low-latency taker could buy undervalued binary tokens (e.g., purchasing YES shares at 0.50 USDC when fair probability is 0.65 USDC) and either hold to expiration or capture post-burst quote drift.

### Why It Seemed Plausible
1. **Structural Market Asymmetry**: Decentralized prediction markets have historically featured retail participants, lower liquidity, and fragmented liquidity providers compared to multi-billion-dollar spot and perpetual order books.
2. **Exogenous Information Lead**: Price discovery for Bitcoin and Ethereum occurs primarily on centralized perp/spot exchanges. Polymarket is a price-taker venue reliant on external price oracles.
3. **Apparent Digital Option Math**: A binary call option's theoretical value is given analytically by P(S_T >= K) = Phi(d2). In theory, feeding real-time spot price S, strike K, annualized realized volatility sigma, and time-to-expiry T yields an exogenous fair probability completely independent of Polymarket book quotes.

---

## 2. Development Timeline and Premature Infrastructure Expansion

A critical failure of the project's engineering process was the rapid escalation of operational infrastructure prior to validating the underlying statistical premise.

Between initial inception and strategy shelving, the following complex systems were built, refined, and deployed:
- Multi-exchange live WebSocket ingestion feeds with automatic regional failover (handling Malaysian ISP blocks on Binance by cascading through Bybit, OKX, HTX, and Coinbase).
- A 5-agent asynchronous message-bus architecture (The Eyes, The Brain, The Shield, The Hands, The Ledger).
- An interactive Streamlit web management dashboard featuring real-time telemetry, risk parameter synchronizers, and pipeline health indicators.
- Live Telegram alerting bots for trade notifications and circuit-breaker triggers.
- Secondary signal filters including Order Flow Imbalance (OFI) calculations, cross-venue spot consensus filters, and dynamic Take-Profit / Stop-Loss state machines.
- A simulated EIP-712 cryptographic signature dispatch system.

**The Reality of the Data Foundation:**  
Throughout the entire development of these systems, the empirical dataset in `research/data/momentum_events.csv` contained exactly **one synthetic test row** with an unresolved outcome. Zero live trades were executed. Zero positions were settled. Massive engineering effort was expended building downstream delivery vehicles, risk gates, and UI dashboards on top of an unvalidated hypothesis that had not passed even the most basic preliminary data checks.

---

## 3. The Five Empirical Findings (F1–F5)

The decision to shelve the strategy is driven by five independent, empirical findings:

### F1. Target Markets Do Not Exist
Polymarket Gamma API discovery, once strictly filtered to the intended operational tradeable window (120s <= T <= 600s), returns an empty list. Polymarket does not list active crypto binary contracts maturing in ultra-short 2-to-10 minute horizons. The contracts available mature in days, weeks, or months. The strategy's core premise requires financial instruments that do not exist on the venue.

### F2. The Tradeable Window Is Where the Model Is Weakest
As time-to-expiry T -> 0, the Black-Scholes binary option pricing formula Phi(d2) degenerates from a smooth probabilistic curve into a discontinuous step function. At T = 120s, varying only the volatility input sigma across a realistic empirical range (0.40 to 3.12 annualized) swings the calculated fair value across **33.6 cents** (e.g., from 0.48 to 0.816). The strategy's minimum target profit edge is **3.5 cents**. The uncertainty stemming from a single parameter input exceeds the target edge by approximately **10x**, rendering the model unable to distinguish between genuine alpha and estimation noise.

### F3. The Volatility Estimate Is Biased by the Trigger That Selects It
The trading trigger requires a spot price move of >= 0.3% over a 60-second window. The model then estimated realized volatility sigma over that exact same 60-second window. Any 60-second sample selected specifically because it contains an anomalous directional burst will mathematically exhibit an extreme volatility spike. In recorded empirical telemetry, a modest 0.45% spot burst produced an annualized volatility of **realized_vol_60s = 3.1274 (312% annualized)**. This bias is structural and cannot be tuned away: the selection rule and parameter estimator share the same window.

### F4. Zero Validation Data Exists
`research/data/momentum_events.csv` contains 1 synthetic placeholder row. The pre-committed validation criteria in `research/GATE.md` required a minimum sample of N = 100 verified, resolved empirical momentum events before any execution logic could be enabled. Real trades executed: 0. Settled trades: 0.

### F5. Every 'Validation' Signal Produced So Far Was a Bug Reflecting Its Own Input
The dashboard's Brier Calibration Tournament reported a Model Brier score of **0.0001** versus a Market Brier score of **0.2835** across 1,639 contract evaluations, prompting the system to render `"STATISTICAL EDGE VERIFIED"`.  
The score of 0.0001 is algebraically identical to (0.99 - 1.0)^2. The model collapsed to its upper clamp (0.99) whenever spot > strike, and the tournament resolver recorded the outcome as 1.0 whenever spot >= strike. Both sides read the exact same variable at the exact same moment. No forecasting occurred; the system evaluated a single tautology 1,639 times. The reported 'skill delta' of +0.2834 was the arithmetic distance between an internal equality bug and real prediction data.

---

## 4. Four Transferable Failure Patterns

### (a) Circular Edge
- **Definition & Repo Manifestation**: Theoretical value was computed as a function of the market ask price plus an assumed edge or adjustment, reducing the apparent statistical edge to an arithmetic tautology where the market price cancels out:
  ```python
  # Manifestation in earlier revisions:
  model_fair_prob = min(0.99, best_ask + theoretical_edge_boost)
  signal = (model_fair_prob - best_ask) >= min_delta  # reduces to: theoretical_edge_boost >= min_delta
  ```
  The system appeared to detect a positive spread over the market, but the calculation merely reflected the hardcoded adjustment added to the market's own quote.
- **General Test**: Does the fair-value function take a market price as an input? If yes, it is not an independent fair-value function. Any pricing model whose output correlates directly with the quote it seeks to arbitrage is measuring circularity, not alpha.

### (b) Step-Function Artifact
- **Definition & Repo Manifestation**: A corrupted or static time-to-expiry input ($T=300\text{s}$ hardcoded on contracts maturing months in the future, or evaluating near-zero $T$) collapsed a continuous cumulative normal distribution $\Phi(d_2)$ into a degenerate Heaviside step function:
  ```python
  # When T is small or misconfigured:
  d2 = (math.log(spot / strike) - 0.5 * vol**2 * T) / (vol * math.sqrt(T))
  # As T -> 0 or spot != strike, d2 explodes to +/- infinity, forcing Phi(d2) to clamp at 0.01 or 0.99
  ```
  At $T=120\text{s}$, varying volatility across a plausible empirical range (0.40 to 3.12 annualized) swings the fair value by 33.6 cents across the 50-cent inflection point, dwarfing the strategy's 3.5-cent profit threshold by nearly 10x. The largest apparent edges appeared precisely where the model's sensitivity was most pathological and broken.
- **General Test**: Plot the model output across the entire input domain. A model that only ever emits values near its minimum/maximum clamps (e.g., 0.01 or 0.99) or whose derivative $\partial P / \partial \sigma$ explodes relative to execution spread is broken.

### (c) Selection-Induced Estimator Bias
- **Definition & Repo Manifestation**: The momentum filter triggered signals only after a $\ge 0.3\%$ spot price move occurred within a 60-second window, and the volatility estimator then sampled that exact same 60-second window to price the option. By conditioning data selection on a realized extreme return, the volatility estimator was structurally guaranteed to measure an outlier spike:
  - Recorded repo empirical sample: `realized_vol_60s = 3.1274` (312% annualized) derived from a single 0.45% move.
  - This bias cannot be eliminated by tuning thresholds; it is mathematical: the selection rule and the parameter estimator shared the identical observation window.
- **General Test**: Does any pricing or risk input get estimated from data chosen by the entry trigger condition? If the entry condition selects for variance, the volatility estimator must sample an independent, unconditioned lookback window (or an exogenous implied volatility surface).

### (d) Tautological Validation
- **Definition & Repo Manifestation**: The predictor and the tournament resolver evaluated the exact same underlying spot variable at the same point in time. The model emitted 0.99 when $\text{spot} > \text{strike}$, and the resolver marked the outcome as 1.0 because $\text{spot} \ge \text{strike}$. 
  - Result: The Brier score was calculated as $(0.99 - 1.0)^2 = 0.0001$ across all 1,639 recorded records with zero variance.
  - The dashboard rendered "STATISTICAL EDGE VERIFIED" with a reported skill delta of $+0.2834$ over the market ($0.0001 \text{ vs } 0.2835$), celebrating what was simply one number subtracted from itself 1,639 times.
- **General Test**: A validation metric that is near-perfect (such as a Brier score $< 0.01$ or a Sharpe ratio $> 10$ on binary financial events) is a bug report, not an empirical result. Calibration routines must enforce hard assertions that reject suspiciously zero-loss outcomes.

---

## 5. Early Detection Analysis and Costs

Every fatal failure in this project could have been discovered at minimal engineering cost before building complex multi-agent frameworks:

| Failure | Detection Mechanism | Cost to Catch |
| :--- | :--- | :--- |
| **F1 (No Markets)** | Inspect Polymarket Gamma API response for contracts with `endDate - now <= 600s`. | 1 HTTP GET request / 5 minutes. |
| **F2 (Step-Function Vol Sensitivity)** | Plot partial derivative $\partial \Phi(d_2) / \partial \sigma$ across $T \in [60, 600]$ in a 10-line Python script. | 15 minutes of elementary analysis. |
| **F3 (Selection-Induced Bias)** | Audit parameter dependencies: verify whether feature extraction window overlaps with trigger window. | 10 minutes of code review. |
| **F4 (Empty Dataset)** | Pre-commit gate in CI: block execution logic until CSV row count with non-null labels $\ge 100$. | 5 lines of shell or Python / 5 minutes. |
| **F5 (Tautological Brier Validation)** | Assert `brier_score >= 0.01` in calibration unit tests, flagging zero-variance predictions as fatal bugs. | 5 minutes of unit test authoring. |

---

## 6. Pre-Commitment Validation & Capital Outcome

`research/GATE.md` was established at the outset of the research initiative to define explicit, falsifiable quantitative criteria. It mandated that unless positive Brier calibration skill, sufficient book depth, and verifiable quote latency lag were statistically demonstrated over $N \ge 100$ real events, the strategy must be shelved immediately.

Shelving a quantitative trading strategy upon negative empirical findings is not a project failure; it is the intended, successful operation of scientific risk governance.

- **Total Capital Lost:** **$0.00**
- **Total Real Capital Deployed:** **$0.00**

Because execution was locked behind verification gates and no private keys were ever provisioned, the project successfully protected 100% of capital against flawed theoretical assumptions.

---

## 7. Preserved Reusable Components

The following modules represent solid engineering work and should be retained for future quantitative research independent of this strategy:

1. **`research/fair_value.py`**: A correct, closed-form Black-Scholes binary digital option pricing implementation ($P = \Phi(d_2)$) accompanied by an honest assumptions docstring. The code was mathematically correct; it was simply fed misaligned inputs (pathological $T$ and biased $\sigma$).
2. **5-Agent Message-Bus Architecture (`agents/`, `core/message_bus.py`)**: A clean, modular asynchronous pub/sub agent topology decoupling data ingestion, evaluation, risk guardrails, execution, and ledger auditing.
3. **Multi-Exchange Fallback Ingestion (`core/live_feeds.py`)**: Robust WebSocket and REST connection management with automatic regional failover (handling ISP blocks by pivoting seamlessly between Bybit, OKX, HTX, and Coinbase).
4. **Pre-Commitment Gate Template (`research/GATE.md`)**: A disciplined quantitative governance framework encoding explicit Go/Shelve criteria to prevent sunk-cost fallacy.
5. **Null-Model Backtest Harness**: The empirical calibration tournament pattern comparing model forecast Brier scores directly against prevailing market pricing.
