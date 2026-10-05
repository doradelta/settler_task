"""Problem 2: which auctions to quote when payments differ in size and capital is finite.

A quote of size a earns π(a) = α·a − β in expectation (gas is a fixed cost per fill, so β > 0: small payments
lose money) and ties up a·T of capital-time, T being the seconds a payment stays reserved, then locked.
Choosing acceptance rates x(a) ≤ λ·f(a) to maximise Σ x(a)·π(a) subject to Σ x(a)·a·T ≤ C is a fractional
knapsack: take auctions in order of yield π(a)/(a·T), which rises with a. So the optimal policy is a size
threshold, quote iff a ≥ a_min, and the LP's dual λ* = yield at a_min is the bid price: the return every unit
of capital must earn per second. Sizes are lognormal around the brief's 1,000.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import optimize, stats

from .pricing import Market, expected_pnl


@dataclass(frozen=True)
class Sizes:
    median: float = 1000.0
    log_sd: float = 0.8          # lognormal spread: 0.8 puts the middle 80 % of payments between 360 and 2,800

    def mean_above(self, x: float) -> float:
        """E[a · 1{a ≥ x}] for a lognormal: closed form."""
        mu, sd = math.log(self.median), self.log_sd
        return math.exp(mu + sd * sd / 2) * stats.norm.sf((math.log(max(x, 1e-9)) - mu - sd * sd) / sd)

    def share_above(self, x: float) -> float:
        return stats.norm.sf((math.log(max(x, 1e-9)) - math.log(self.median)) / self.log_sd)

    def draw(self, rng, n: int):
        return rng.lognormal(math.log(self.median), self.log_sd, n)


def profit_line(markup: float, window: float, mk: Market) -> tuple[float, float]:
    """(α, β): expected profit of a quote of size a is α·a − β."""
    pi1, pi2 = expected_pnl(markup, window, mk, 1.0)[0], expected_pnl(markup, window, mk, 2.0)[0]
    return pi2 - pi1, pi2 - 2 * pi1


def held_seconds(markup: float, window: float, mk: Market) -> float:
    """T: expected seconds one payment's capital is reserved, then locked, per quote."""
    q = expected_pnl(markup, window, mk)[1]
    settle = mk.latency + mk.lock
    return (1 - mk.p_informed) * (window / 2 + settle) + mk.p_informed * (window + q * settle)


@dataclass(frozen=True)
class BidPrice:
    min_size: float          # quote iff min_size ≤ size (≤ capital: a single payment we cannot fund is declined anyway)
    bid_price: float         # λ*: profit each unit of capital must earn per second (0 when capital is slack)
    capital_binds: bool
    accept_share: float      # share of auctions quoted
    profit_per_s: float      # fluid (LP) profit rate of the threshold policy: an upper bound, exact as capital ≫ payment
    utilisation: float


def bid_price(markup: float, window: float, mk: Market, capital: float, arrival_rate: float, sizes: Sizes = Sizes()) -> BidPrice:
    a, b = profit_line(markup, window, mk)
    T = held_seconds(markup, window, mk)
    mean = lambda x: sizes.mean_above(x) - sizes.mean_above(capital)           # E[a; x ≤ a ≤ C]
    share = lambda x: sizes.share_above(x) - sizes.share_above(capital)
    usage = lambda x: arrival_rate * T * mean(x)                                  # capital in use with threshold x (Little)
    a_gas = b / a if a > 0 else math.inf                                          # size below which a quote loses money
    if not math.isfinite(a_gas) or a_gas >= capital:
        return BidPrice(math.inf, 0.0, False, 0.0, 0.0, 0.0)
    if usage(a_gas) <= capital:
        x, lam, binds = a_gas, 0.0, False
    else:
        x = optimize.brentq(lambda v: usage(v) - capital, a_gas, capital)
        lam, binds = (a * x - b) / (x * T), True
    profit = arrival_rate * (a * mean(x) - b * share(x))
    return BidPrice(x, lam, binds, share(x), profit, min(1.0, usage(x) / capital))
