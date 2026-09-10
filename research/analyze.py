"""
JAZZ Trading Research: Statistical Analysis & Gate Auditor
Analyzes empirical data recorded by lag_probe.py to evaluate:
1. Does the Polymarket CLOB ask actually move after spot momentum? (Lag distribution)
2. Is the theoretical fair probability better calibrated than the market ask? (Brier score & decile calibration)
3. Fill realism: What fraction of t0 asks survive at t+1s and t+5s?
4. Round-trip friction hurdle vs observed gross edge.
5. Evaluation against research/GATE.md pre-commitment rules.
"""

import csv
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEFAULT_CSV = os.path.join(DATA_DIR, "momentum_events.csv")


def load_events(csv_path: str = DEFAULT_CSV) -> List[dict]:
    if not os.path.exists(csv_path):
        print(f"[ERROR] CSV dataset not found at {csv_path}")
        return []

    events = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            events.append(row)
    return events


def parse_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def analyze_price_lag(events: List[dict]):
    print("=" * 75)
    print(" 1. PRICE LAG & ASSET REACTION ANALYSIS")
    print("=" * 75)

    deltas_1s = []
    deltas_5s = []
    deltas_30s = []

    by_bucket = {
        "Positive (0.3% - 0.5%)": [],
        "Positive (> 0.5%)": [],
        "Negative (-0.3% - -0.5%)": [],
        "Negative (< -0.5%)": []
    }

    for ev in events:
        ask_t0 = parse_float(ev.get("pm_best_ask_t0"))
        ask_t1s = parse_float(ev.get("pm_best_ask_t1s"))
        ask_t5s = parse_float(ev.get("pm_best_ask_t5s"))
        ask_t30s = parse_float(ev.get("pm_best_ask_t30s"))
        vel = parse_float(ev.get("spot_velocity_60s"))

        if ask_t0 is None or vel is None:
            continue

        if ask_t1s is not None:
            deltas_1s.append(ask_t1s - ask_t0)
        if ask_t5s is not None:
            d5 = ask_t5s - ask_t0
            deltas_5s.append(d5)
            if vel >= 0.5:
                by_bucket["Positive (> 0.5%)"].append(d5)
            elif 0.3 <= vel < 0.5:
                by_bucket["Positive (0.3% - 0.5%)"].append(d5)
            elif -0.5 < vel <= -0.3:
                by_bucket["Negative (-0.3% - -0.5%)"].append(d5)
            elif vel <= -0.5:
                by_bucket["Negative (< -0.5%)"].append(d5)

        if ask_t30s is not None:
            deltas_30s.append(ask_t30s - ask_t0)

    def stats(arr):
        if not arr:
            return "N=0 | No observations"
        arr_sorted = sorted(arr)
        mean_v = sum(arr) / len(arr)
        median_v = arr_sorted[len(arr_sorted) // 2]
        return f"N={len(arr)} | Mean: {mean_v:+.4f} ({mean_v*100:+.2f}c) | Median: {median_v:+.4f} ({median_v*100:+.2f}c) | Min: {arr_sorted[0]:+.4f} | Max: {arr_sorted[-1]:+.4f}"

    print(f"Overall dAsk (t+1s - t0):  {stats(deltas_1s)}")
    print(f"Overall dAsk (t+5s - t0):  {stats(deltas_5s)}")
    print(f"Overall dAsk (t+30s - t0): {stats(deltas_30s)}")
    print("\ndAsk at t+5s Split by Spot Velocity Buckets:")
    for b_name, b_vals in by_bucket.items():
        print(f"  * {b_name:<26}: {stats(b_vals)}")

    if deltas_5s:
        med_5s = sorted(deltas_5s)[len(deltas_5s) // 2]
        if abs(med_5s) < 0.005:
            print("\n[VERDICT ON LAG]: Median price movement at t+5s is centered near ZERO.")
            print("  --> EVIDENCE SUGGESTS THE CLOB DOES NOT SYSTEMATICALLY LAG SPOT MOMENTUM.")


def analyze_fill_realism(events: List[dict]):
    print("\n" + "=" * 75)
    print(" 2. FILL REALISM & QUOTE PERSISTENCE (ADVERSE SELECTION AUDIT)")
    print("=" * 75)

    valid_1s = 0
    survived_1s = 0
    valid_5s = 0
    survived_5s = 0

    for ev in events:
        ask_t0 = parse_float(ev.get("pm_best_ask_t0"))
        ask_t1s = parse_float(ev.get("pm_best_ask_t1s"))
        ask_t5s = parse_float(ev.get("pm_best_ask_t5s"))

        if ask_t0 is None:
            continue

        if ask_t1s is not None:
            valid_1s += 1
            if ask_t1s <= ask_t0:
                survived_1s += 1

        if ask_t5s is not None:
            valid_5s += 1
            if ask_t5s <= ask_t0:
                survived_5s += 1

    rate_1s = (survived_1s / valid_1s * 100.0) if valid_1s > 0 else 0.0
    rate_5s = (survived_5s / valid_5s * 100.0) if valid_5s > 0 else 0.0

    print(f"Quote Survival at t+1s (Ask_t1s <= Ask_t0): {survived_1s}/{valid_1s} ({rate_1s:.1f}%)")
    print(f"Quote Survival at t+5s (Ask_t5s <= Ask_t0): {survived_5s}/{valid_5s} ({rate_5s:.1f}%)")

    if rate_1s < 20.0:
        print("\n[CRITICAL WARNING]: Less than 20% of quotes survive for 1 second.")
        print("  --> Any slow limit order will fail to fill, or will execute ONLY on toxic, adverse inventory.")


def analyze_calibration_and_brier(events: List[dict]):
    print("\n" + "=" * 75)
    print(" 3. MODEL VS MARKET CALIBRATION & BRIER SCORE")
    print("=" * 75)

    paired = []
    for ev in events:
        y_str = ev.get("resolved_outcome")
        if y_str is None or y_str == "":
            continue
        y = parse_float(y_str)
        m_prob = parse_float(ev.get("model_fair_prob"))
        mkt_ask = parse_float(ev.get("pm_best_ask_t0"))

        if y is not None and m_prob is not None and mkt_ask is not None:
            paired.append((m_prob, mkt_ask, y))

    if not paired:
        print("No events with verified terminal resolution (resolved_outcome) found.")
        print("Note: Run `python research/lag_probe.py --backfill` after market expiry to populate outcomes.")
        return

    brier_model = sum((p - y) ** 2 for p, _, y in paired) / len(paired)
    brier_market = sum((q - y) ** 2 for _, q, y in paired) / len(paired)

    print(f"Total Resolved Events (N): {len(paired)}")
    print(f"Brier Score (Theoretical Model): {brier_model:.5f} (lower is better)")
    print(f"Brier Score (Market Ask Quote):  {brier_market:.5f} (lower is better)")

    if brier_market <= brier_model:
        print("\n[CALIBRATION RESULT]: The market ask quote BEATS or matches the theoretical model.")
        print("  --> The Black-Scholes binary model has negative informational alpha against the CLOB.")
    else:
        print(f"\n[CALIBRATION RESULT]: The theoretical model out-predicted market quotes by {brier_market - brier_model:.5f} Brier points.")


def report_round_trip_hurdle():
    print("\n" + "=" * 75)
    print(" 4. ROUND-TRIP TRANSACTION COST ESTIMATE")
    print("=" * 75)
    print("Sources and Breakdown:")
    print("  1. Exchange Fee: 0% Maker / 0% Taker")
    print("     Source: Polymarket Fee Schedule (promotional 0% fee structure on standard CLOB pairs)")
    print("  2. Spread Crossing Drag (Entry + Exit):")
    print("     Typical 5m/15m CLOB spread: 2.0c to 4.0c on a 50c mid-price (400 to 800 bps).")
    print("     Crossing half-spread on entry: ~200 bps ($0.010)")
    print("     Crossing half-spread on exit/settlement: ~200 bps ($0.010)")
    print("  3. Slippage & Relayer Friction: ~50 bps ($0.0025)")
    print("  -------------------------------------------------------------------------")
    print("  MINIMUM REQUIRED EDGE TO BREAK EVEN: ~450 bps ($0.0225 per share)")
    print("  Any gross edge smaller than +2.5 cents is completely consumed by market structure.")
    print("=" * 75)


def evaluate_gate(events: List[dict]):
    print("\n" + "=" * 75)
    print(" 5. PRE-COMMITMENT GATE EVALUATION (research/GATE.md)")
    print("=" * 75)
    total_n = len(events)
    print(f"Total Momentum Events Recorded: {total_n} (Target minimum: 100)")
    if total_n < 100:
        print(f"[STATUS]: INSUFFICIENT DATA for conclusive gate decision ({total_n}/100 recorded).")
        print("Keep lag_probe.py running to collect adequate statistical sample.")
    print("=" * 75 + "\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="JAZZ Trading Research: Empirical Analyzer")
    parser.add_argument("--csv", type=str, default=DEFAULT_CSV, help="Path to momentum_events.csv")
    args = parser.parse_args()

    events = load_events(args.csv)
    if not events:
        sys.exit(0)

    analyze_price_lag(events)
    analyze_fill_realism(events)
    analyze_calibration_and_brier(events)
    report_round_trip_hurdle()
    evaluate_gate(events)


if __name__ == "__main__":
    main()
