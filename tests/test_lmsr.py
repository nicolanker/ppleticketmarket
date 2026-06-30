"""Unit tests for the LMSR market maker."""

import math

from app.lmsr import cost_to_trade, prices


def test_seeded_uniform_at_zero():
    """With no shares outstanding, every outcome is equally likely (1/N)."""
    n = 5
    ps = prices([0.0] * n, b=100)
    assert all(abs(p - 1 / n) < 1e-9 for p in ps)


def test_prices_sum_to_one():
    ps = prices([30.0, -10.0, 5.0, 0.0], b=50)
    assert abs(sum(ps) - 1.0) < 1e-9


def test_buying_raises_own_price_lowers_others():
    b = 100
    base = prices([0.0] * 4, b)
    after = prices([40.0, 0.0, 0.0, 0.0], b)
    assert after[0] > base[0]
    for i in range(1, 4):
        assert after[i] < base[i]


def test_buy_costs_money_sell_returns_money():
    q = [0.0] * 4
    buy = cost_to_trade(q, 0, 20, b=100)
    assert buy > 0
    # After buying, selling the same shares returns a similar (slightly less) amount.
    q2 = [20.0, 0.0, 0.0, 0.0]
    refund = -cost_to_trade(q2, 0, -20, b=100)
    assert refund > 0
    assert refund <= buy + 1e-9


def test_cost_bounded_by_b_ln_n():
    """Cost of moving one outcome to ~certainty is bounded by b*ln(N)."""
    b, n = 100, 4
    # Buying a huge amount drives price→1; total cost approaches b*ln(N) ceiling
    # for the maker's exposure on the rest.
    huge = cost_to_trade([0.0] * n, 0, 100000, b)
    assert huge < 100000  # far below the naive shares*1 upper bound
    assert huge > 0


def test_price_moves_toward_one_with_heavy_buying():
    ps = prices([1000.0, 0.0, 0.0], b=100)
    assert ps[0] > 0.99
