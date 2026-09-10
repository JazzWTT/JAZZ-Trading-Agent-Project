"""
Unit tests for research/fair_value.py
Asserts mathematical properties of Black-Scholes binary option pricing.
"""

import unittest
from research.fair_value import (
    calculate_binary_fair_probability,
    calculate_realized_volatility_60s,
    standard_normal_cdf
)


class TestFairValueModel(unittest.TestCase):
    def test_at_the_money_approx_half(self):
        """Spot == Strike at short expiry should produce ~0.50."""
        spot = 60000.0
        strike = 60000.0
        secs_remaining = 300.0  # 5 minutes
        vol = 0.60  # 60% annualized volatility

        prob_yes = calculate_binary_fair_probability(spot, strike, secs_remaining, vol, "YES")
        prob_no = calculate_binary_fair_probability(spot, strike, secs_remaining, vol, "NO")

        self.assertIsNotNone(prob_yes)
        self.assertIsNotNone(prob_no)
        # Should be extremely close to 0.50 (within 0.005)
        self.assertAlmostEqual(prob_yes, 0.50, delta=0.005)
        self.assertAlmostEqual(prob_no, 0.50, delta=0.005)
        self.assertAlmostEqual(prob_yes + prob_no, 1.0, places=6)

    def test_monotonicity_with_spot(self):
        """As spot increases above strike, YES probability must monotonically increase."""
        strike = 60000.0
        secs = 300.0
        vol = 0.50

        # Steps around the money where probability transitions smoothly
        spots = [59800.0, 59900.0, 59950.0, 60000.0, 60050.0, 60100.0, 60200.0]
        probs = [calculate_binary_fair_probability(s, strike, secs, vol, "YES") for s in spots]

        for i in range(1, len(probs)):
            self.assertGreater(
                probs[i], probs[i - 1],
                f"Monotonicity failed between spot={spots[i-1]} ({probs[i-1]}) and spot={spots[i]} ({probs[i]})"
            )

    def test_in_the_money_and_out_of_money(self):
        """Deep ITM should approach 1.0; Deep OTM should approach 0.0."""
        strike = 60000.0
        secs = 300.0
        vol = 0.40

        deep_itm = calculate_binary_fair_probability(65000.0, strike, secs, vol, "YES")
        deep_otm = calculate_binary_fair_probability(55000.0, strike, secs, vol, "YES")

        self.assertGreater(deep_itm, 0.99)
        self.assertLess(deep_otm, 0.01)

    def test_realized_volatility_calculation(self):
        """Verify empirical volatility calculation from series."""
        base = 60000.0
        prices = [base * (1.0 + 0.0005 * ((-1) ** i)) for i in range(60)]
        vol = calculate_realized_volatility_60s(prices, interval_seconds=1.0)
        self.assertIsNotNone(vol)
        self.assertGreater(vol, 0.0)

    def test_expired_market_boundary(self):
        """At secs_remaining <= 0, outcome is deterministic."""
        self.assertEqual(calculate_binary_fair_probability(60001.0, 60000.0, 0, 0.5, "YES"), 1.0)
        self.assertEqual(calculate_binary_fair_probability(59999.0, 60000.0, 0, 0.5, "YES"), 0.0)
        self.assertEqual(calculate_binary_fair_probability(59999.0, 60000.0, 0, 0.5, "NO"), 1.0)


if __name__ == "__main__":
    unittest.main()
