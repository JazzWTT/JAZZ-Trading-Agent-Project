# JAZZ Trading System — Phase 1 Pre-Commitment Gate

**Objective**: Determine empirically whether short-term (5m/15m) Polymarket crypto binary contracts lag external spot momentum (BTC, ETH, SOL) sufficiently to generate positive expected value after adverse selection, spreads, and execution latency.

**Rule of Pre-Commitment**: The criteria below are decided **in advance of data collection**. Shelving the strategy upon failing these gates is considered a successful scientific outcome, preventing capital allocation into an unviable premise.

---

## 1. The Core Hypothesis Under Test

> "When spot crypto moves $\ge 0.3\%$ within a 60-second window, Polymarket CLOB ask quotes for corresponding directional contracts remain unadjusted for $\ge 1$ second, permitting non-colocated participants to capture positive expectancy."

If market makers adjust quotes within milliseconds via direct exchange feeds or cancel orders upon spot surges, any fill received by a slow momentum strategy is selected adversely (i.e. fills only happen when momentum is failing or reversing).

---

## 2. Sample Size Requirement

A minimum of **$N = 100$ independent momentum events** across BTC, ETH, and SOL must be recorded with both $t_0, t+1\text{s}, t+5\text{s}, t+30\text{s}$ quote tracking and terminal settlement backfill.

---

## 3. Phase 2 Justification Gate (ALL Must Pass)

To justify advancing to Phase 2 (Live Paper Trading or Micro-Capital Execution), the recorded dataset must meet all four quantitative bars:

| ID | Metric | Threshold | Economic Rationale |
| :--- | :--- | :--- | :--- |
| **G-1** | **Quote Survival Rate ($t+1\text{s}$)** | $\ge 35.0\%$ | Fraction of events where $\text{Ask}_{t+1\text{s}} \le \text{Ask}_{t_0}$. If quotes vanish within 1s, retail API orders will suffer 100% reject or fill into adverse depth. |
| **G-2** | **Post-Event Directional Drift** | $\text{Median}(\Delta \text{Ask}_{t+5\text{s}}) \ge +0.020$ ($+2.0\text{¢}$) | The market must demonstrably reprice in the direction of the momentum impulse. If the median drift is zero, there is no latency to exploit. |
| **G-3** | **Net Edge After Frictions** | $\text{Mean}(\text{Edge}_{\text{net}}) \ge +0.025$ ($+2.5\text{¢}$) | $\text{Edge}_{\text{net}} = (\text{FairProb} - \text{Ask}_{t_0}) - \text{HalfSpread} - 0.005$ (buffer for slippage). Must withstand the wide bid-ask spread of binary books. |
| **G-4** | **Model Calibration Outperformance** | $\text{Brier}_{\text{model}} < \text{Brier}_{\text{market}} - 0.015$ | The fair-value model must predict terminal outcome $(Y \in \{0, 1\})$ strictly better than the pre-burst market price. |

---

## 4. Immediate Shelve Gate (ANY Triggers Immediate Shelve)

If any single condition below is met, the strategy is declared non-viable and **shelved without code deployment**:

1. **S-1 (No Lag / Instant Reaction)**:
   $\text{Median}(\Delta \text{Ask}_{t+1\text{s}}) \le 0.000$ OR Quote Survival Rate at $t+1\text{s} < 15\%$.
   *Meaning*: Polymarket market makers cancel or repriced within sub-second intervals. There is no actionable retail latency.

2. **S-2 (Market Efficiency / Inverse Selection)**:
   $\text{Brier}_{\text{market}} \le \text{Brier}_{\text{model}}$.
   *Meaning*: Market quotes at $t_0$ are better calibrated to the terminal expiry probability than the Black-Scholes binary model. Trading against the market price yields negative alpha.

3. **S-3 (Spread Prohibitive)**:
   Median top-of-book spread on target 5m/15m markets exceeds **$300\text{ bps}$** ($> \$0.015$ on a $\$0.50$ mid).
   *Meaning*: Bid-ask drag completely consumes theoretical edge.

4. **S-4 (Phantom Liquidity)**:
   Fewer than $20\%$ of momentum events have top-3 ask depth $\ge \$500\text{ USDC}$.
   *Meaning*: Available liquidity cannot support minimum order sizes without moving price into negative expectancy.
