# JAZZ Trading United Nation (JAZZ-UN)

```
STATUS: SHELVED — strategy retired on evidence, 2026-09-13.
This system never traded. Capital deployed: $0. See POSTMORTEM.md.
```

---

## Strategy Status & Decommissioning

This repository previously housed experimental code investigating whether short-term (5m/15m) cryptocurrency prediction markets on Polymarket lagged high-frequency spot momentum on centralized exchanges.

Following empirical validation against pre-committed quantitative gates (`research/GATE.md`), the strategy has been **permanently shelved and decommissioned**.

### Why the Strategy Was Retired
1. **Target Markets Do Not Exist**: Polymarket does not list active crypto binary contracts maturing in the intended 120s–600s tradeable window.
2. **Model Instability Near Expiry**: Black-Scholes binary option pricing degenerates toward a step function near expiry. Parameter uncertainty in volatility dwarfs the targeted edge by ~10x.
3. **Structural Estimator Bias**: Volatility was estimated from the same 60-second window that triggered the momentum signal, creating a structural upward bias.
4. **Zero Empirical Validation Data**: No live trades were executed, and the event dataset contained only 1 synthetic row.
5. **Tautological Validation**: The reported Brier calibration score (0.0001) was an artifact of the model and the resolver reading the same spot price variable simultaneously.

For a complete technical analysis of the failure patterns and lessons learned, read **[POSTMORTEM.md](POSTMORTEM.md)**.

---

## Decommissioning & Safety Enforcement
- **Order Execution**: Permanently disabled. `agents/agent3_hands.py` raises `RuntimeError` on any order execution attempt.
- **Bot Daemon**: `bot_service.py` terminates immediately upon launch with a shelved notice.
- **Web UI**: Bot start controls, kill-switch triggers, risk parameter sync sliders, and false calibration tournament badges have been permanently removed from `app.py`.
- **Audit Ledger**: Contaminated Brier calibration data has been truncated to 0 rows.
- **Keys & Credentials**: No wallets, private keys, or CLOB client signing credentials exist in this repository. Total capital deployed is $0.

---

## Reusable Components
While the trading strategy is retired, several architecture components remain useful for future research:
- **`research/fair_value.py`**: Closed-form Black-Scholes binary option digital call/put pricing model.
- **5-Agent Async Pipeline**: Decoupled message-bus architecture (`agents/` and `core/message_bus.py`).
- **`core/live_feeds.py`**: Multi-exchange feed harmonizer with automatic regional fallback (Bybit, OKX, HTX, Coinbase).
- **`research/GATE.md`**: Pre-commitment quantitative governance template.
- **Null-Model Tournament Harness**: Framework for scoring probabilistic forecasts against market prices.
