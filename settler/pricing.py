"""Problem 1: the fair markup for a firm quote held open W seconds.

A firm quote is a call the originator holds for free: strike = our price, expiry = award_deadline.
m* solves   (1-p)·E[profit | uninformed] + p·E[profit | informed] - carry = 0,
where m enters twice: as revenue and as the strike the informed originator exercises against.
Returns are Student-t with ν degrees of freedom and variance σ²W; ν = ∞ is the Gaussian limit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
from scipy import optimize, stats

SECONDS_PER_YEAR = 31_557_600.0


@dataclass(frozen=True)
class Market:
    notional: float = 1000.0        # N, source units per payment
    sigma: float = 2e-4             # rate volatility per sqrt(second) (2 bp)
    nu: float = 4.0                 # Student-t degrees of freedom; math.inf = Gaussian
    p_informed: float = 0.3         # originators who award only if the rate beat the quote
    gas_mean: float = 12.5          # E[gas] per fill, source units (spec: U(5, 20))
    latency: float = 24.0           # L: award -> fulfilment proof (2 Ethereum blocks)
    lock: float = 144.0             # fulfil -> release (12 blocks x 12 s)
    cost_of_capital: float = 0.10   # per year, on the payment a quote ties up

    def with_gas(self, factor: float) -> "Market":
        return replace(self, gas_mean=self.gas_mean * factor)


def tail_call(k: float, s: float, nu: float) -> tuple[float, float]:
    """E[(r - k)+] and P(r > k) for a return r with standard deviation s and Student-t(ν) shape."""
    if s <= 0.0:
        return max(-k, 0.0), float(k < 0.0)
    if math.isinf(nu):
        a = k / s
        return s * (stats.norm.pdf(a) - a * stats.norm.sf(a)), stats.norm.sf(a)
    c = s * math.sqrt((nu - 2.0) / nu)  # scale with variance s²
    a = k / c
    return c * ((nu + a * a) / (nu - 1.0) * stats.t.pdf(a, nu) - a * stats.t.sf(a, nu)), stats.t.sf(a, nu)


def expected_pnl(m: float, window: float, mk: Market) -> tuple[float, float]:
    """Expected profit per quote at markup m, and q = P(informed originator awards)."""
    N, p, K = mk.notional, mk.p_informed, 1.0 + m
    drift = 1.0 + mk.sigma**2 * (window / 4 + mk.latency / 2)  # the spec's log steps carry no -σ²/2
    uninformed = N * (1.0 - drift / K) - mk.gas_mean           # awards at a random time, any price
    call, q = tail_call(m, mk.sigma * math.sqrt(window), mk.nu)
    informed = -(N / K * call + mk.gas_mean * q)                # awards iff the rate beat us: a short call
    held = (1 - p) * (window / 2 + mk.latency + mk.lock) + p * (window + q * (mk.latency + mk.lock))
    carry = mk.cost_of_capital * N * held / SECONDS_PER_YEAR
    return (1 - p) * uninformed + p * informed - carry, q


def fair_markup(window: float, mk: Market) -> float:
    """Break-even markup m*(W); unique because revenue rises in m while the call falls."""
    return optimize.brentq(lambda m: expected_pnl(m, window, mk)[0], 0.0, 0.5, xtol=1e-12)


def gas_floor(mk: Market) -> float:
    """The markup whose revenue N·m/(1+m) pays the expected gas."""
    return mk.gas_mean / (mk.notional - mk.gas_mean)


def realized_sigma(log_returns: np.ndarray, halflife: float = 300.0) -> float:
    """EWMA volatility per sqrt(second): price off what the tape is doing now, not a constant."""
    r = np.asarray(log_returns, dtype=float)
    w = 0.5 ** (np.arange(len(r))[::-1] / halflife)
    return math.sqrt(float(np.sum(w * r * r) / np.sum(w)))
