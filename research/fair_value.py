"""
Binary Option Fair-Value Model for Polymarket Crypto Markets.

Calculates the risk-neutral probability of a binary digital call/put
under a Geometric Brownian Motion (GBM) diffusion framework.

MODEL SPECIFICATION & ASSUMPTIONS:
1. Diffusion: Spot price follows dS_t = r*S_t*dt + sigma*S_t*dW_t.
2. Drift & Rates: Risk-free rate r = 0 given ultra-short expiry (5m to 15m).
3. Driftless Assumption: Assumes no drift in the spot price over short horizons.
4. Volatility: Constant local volatility estimated from empirical 60s window.
5. Distribution: Assumes continuous log-normal returns. Crucially, this
   IGNORES leptokurtic fat tails, volatility clustering, and discrete jump
   processes common in cryptocurrency microstructure.
6. Absolute Rule: This model evaluates ONLY the exogenous state (spot, strike,
   time-to-expiry, realized volatility). It NEVER consumes Polymarket prices.
"""

import math
from typing import List, Optional, Tuple


def standard_normal_cdf(x: float) -> float:
    """Computes the standard normal cumulative distribution function Phi(x)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def calculate_realized_volatility_60s(
    prices: List[float],
    interval_seconds: float = 1.0,
    annualization_factor: float = 31536000.0  # seconds in 365 days
) -> Optional[float]:
    """
    Computes annualized realized volatility from high-frequency spot observations.
    
    Args:
        prices: Sequence of consecutive spot price observations (sampled at interval_seconds).
        interval_seconds: Sampling frequency in seconds.
        annualization_factor: Total seconds in a year (365 * 24 * 3600).
        
    Returns:
        Annualized volatility sigma as a float, or None if insufficient variance/data.
    """
    if not prices or len(prices) < 10:
        return None

    # Calculate log returns: r_t = ln(S_t / S_{t-1})
    log_returns = []
    for i in range(1, len(prices)):
        p_prev = prices[i - 1]
        p_curr = prices[i]
        if p_prev <= 0 or p_curr <= 0:
            continue
        log_returns.append(math.log(p_curr / p_prev))

    n = len(log_returns)
    if n < 9:
        return None

    mean_r = sum(log_returns) / n
    variance = sum((r - mean_r) ** 2 for r in log_returns) / (n - 1)
    if variance <= 1e-16:
        return None

    std_per_interval = math.sqrt(variance)
    # Annualize: sigma = std * sqrt(annualization_seconds / interval_seconds)
    annualized_vol = std_per_interval * math.sqrt(annualization_factor / interval_seconds)
    return annualized_vol


def calculate_binary_fair_probability(
    spot: float,
    strike: float,
    secs_remaining: float,
    annualized_vol: float,
    outcome_side: str = "YES"
) -> Optional[float]:
    """
    Calculates theoretical fair probability of terminal payoff for a binary option:
      YES / UP contract: Payoff $1 if S_T >= K, else $0.
      NO / DOWN contract: Payoff $1 if S_T < K, else $0.
      
    Formula:
      T = secs_remaining / (365 * 24 * 3600)
      d2 = [ln(S / K) - 0.5 * sigma^2 * T] / [sigma * sqrt(T)]
      P(S_T >= K) = Phi(d2)
      P(S_T < K) = 1 - Phi(d2) = Phi(-d2)
      
    Args:
        spot: Current spot price of the underlying asset (> 0).
        strike: Market strike price (> 0).
        secs_remaining: Time to market expiry in seconds.
        annualized_vol: Annualized standard deviation of returns (sigma > 0).
        outcome_side: "YES" (above strike) or "NO" (below strike).
        
    Returns:
        Float in range [0.0, 1.0], or None if inputs are mathematically invalid.
    """
    if spot <= 0 or strike <= 0 or annualized_vol <= 0:
        return None

    # At or past expiry
    if secs_remaining <= 0:
        if outcome_side.upper() == "YES":
            return 1.0 if spot >= strike else 0.0
        else:
            return 1.0 if spot < strike else 0.0

    T_years = secs_remaining / 31536000.0  # 365 days
    vol_sqrt_t = annualized_vol * math.sqrt(T_years)

    if vol_sqrt_t <= 1e-12:
        # Near-zero variance limit: deterministic threshold
        if outcome_side.upper() == "YES":
            return 1.0 if spot >= strike else 0.0
        else:
            return 1.0 if spot < strike else 0.0

    # Under r = 0: d2 = [ln(S/K) - 0.5 * sigma^2 * T] / [sigma * sqrt(T)]
    d2 = (math.log(spot / strike) - 0.5 * (annualized_vol ** 2) * T_years) / vol_sqrt_t

    prob_up = standard_normal_cdf(d2)

    if outcome_side.upper() == "YES":
        return prob_up
    elif outcome_side.upper() == "NO":
        return 1.0 - prob_up
    else:
        raise ValueError(f"Unknown outcome_side: {outcome_side}. Must be 'YES' or 'NO'")


def compute_brier_score(predictions: List[float], outcomes: List[int]) -> float:
    """
    Computes mean Brier Score: 1/N * sum((p_i - y_i)^2).
    Lower is better (0.0 = perfect accuracy, 0.25 = uninformative 50/50 prior).
    """
    if len(predictions) != len(outcomes):
        raise ValueError(f"Length mismatch: {len(predictions)} predictions vs {len(outcomes)} outcomes")
    if not predictions:
        return 0.0
    return sum((p - y) ** 2 for p, y in zip(predictions, outcomes)) / len(predictions)


def evaluate_brier_skill(model_probs: List[float], market_mids: List[float], outcomes: List[int]) -> dict:
    """
    Evaluates whether the Black-Scholes binary model outperforms the market mid-price.
    Returns skill delta: Brier_market - Brier_model (>0 means model has edge).
    """
    if not model_probs or len(model_probs) != len(outcomes) or len(market_mids) != len(outcomes):
        return {
            "n": 0,
            "brier_model": 0.0,
            "brier_market": 0.0,
            "skill_delta": 0.0,
            "has_edge": False,
            "model_beats_market": False
        }

    n = len(outcomes)
    b_model = compute_brier_score(model_probs, outcomes)
    b_mkt = compute_brier_score(market_mids, outcomes)
    delta = b_mkt - b_model

    return {
        "n": n,
        "brier_model": round(b_model, 4),
        "brier_market": round(b_mkt, 4),
        "skill_delta": round(delta, 4),
        "has_edge": delta > 0.0,
        "model_beats_market": delta > 0.0
    }

