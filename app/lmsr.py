"""Logarithmic Market Scoring Rule (LMSR) — a pure, automated market maker.

Used by the play-money "best thesis" prediction market. The maker always
quotes a price for every outcome, so a market exists from the very first second
(seeded uniformly at 1/N), and prices move deterministically as shares are
bought and sold.

Key formulas (q = vector of shares outstanding per outcome, b = liquidity):
    cost(q)   = b * ln( Σ_i exp(q_i / b) )
    price_i   = exp(q_i / b) / Σ_j exp(q_j / b)        (always sums to 1)
    trade C   = cost(q after) - cost(q before)

A buyer of Δ shares of outcome i pays ``cost_to_trade``; selling (Δ < 0) returns
money. Each share of the winning outcome settles to 1 unit; losing shares to 0.
The maker's worst-case subsidy is bounded by ``b * ln(N)``.

This module is intentionally free of any web/DB concerns.
"""

from __future__ import annotations

import math
from typing import List


def prices(q: List[float], b: float) -> List[float]:
    """Current price (implied probability) of each outcome. Sums to 1."""
    scaled = [x / b for x in q]
    m = max(scaled)
    exps = [math.exp(s - m) for s in scaled]  # subtract max for numerical stability
    total = sum(exps)
    return [e / total for e in exps]


def cost(q: List[float], b: float) -> float:
    """LMSR cost-function value for share vector ``q``."""
    scaled = [x / b for x in q]
    m = max(scaled)
    return b * (m + math.log(sum(math.exp(s - m) for s in scaled)))


def cost_to_trade(q: List[float], index: int, delta: float, b: float) -> float:
    """Cost to change outcome ``index`` by ``delta`` shares (negative = sell)."""
    q2 = list(q)
    q2[index] += delta
    return cost(q2, b) - cost(q, b)
