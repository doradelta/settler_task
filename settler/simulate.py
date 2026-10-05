"""The spec's market and two experiments.

Part C  breakeven(): the engine's quote rule at fixed markups m*-1bp, m*, m*+1bp against the Gaussian spec
        market. Mean P&L per quote is affine in 1/(1+m) except through the informed award set, so a parabola
        through three points gives the zero. Unlimited inventory makes every quote independent given the rate
        path, so the rule is evaluated vectorised (identical to the event loop: tests). Noise control: the path
        and its mirror (-Z) are averaged, and gas enters at its known mean (it is independent of fills).
Part A  capacity_run(): the engine with finite capital driven by an event loop, payments of varying size.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, replace
from typing import Optional

import numpy as np
from scipy import stats

from .allocation import Sizes
from .engine import Auction, Engine, Inventory, Quote
from .pricing import SECONDS_PER_YEAR, Market, fair_markup

ARRIVAL_RATE = 2.0  # auctions per second (Poisson)


@dataclass(frozen=True)
class Tape:
    rate: np.ndarray       # R(t) per second, R(0) = 1
    t0: np.ndarray         # auction open times
    informed: np.ndarray   # hidden originator type
    u: np.ndarray          # uninformed award time = t0 + u·window
    deadline: np.ndarray   # fulfillment_deadline
    amount: np.ndarray     # payment size, source units


def spec_market(mk: Market, seconds: float, seed: int, mirror: bool = False, sizes: Optional[Sizes] = None,
                arrival_rate: float = ARRIVAL_RATE) -> Tape:
    """R(t+1) = R(t)·exp(σZ), Poisson auctions, p informed, fulfilment deadlines U(0, 1 h) ahead, payments of N (or `sizes`)."""
    rate_rng, auc_rng = (np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(2))
    z = rate_rng.standard_normal(int(seconds) + 3700) * (-1.0 if mirror else 1.0)
    rate = np.exp(np.concatenate(([0.0], np.cumsum(mk.sigma * z))))
    t0 = np.cumsum(auc_rng.exponential(1.0 / arrival_rate, int(arrival_rate * seconds * 1.05) + 1000))
    t0 = t0[t0 < seconds]
    n = len(t0)
    informed, u, deadline = auc_rng.random(n) < mk.p_informed, auc_rng.random(n), t0 + auc_rng.uniform(0.0, 3600.0, n)
    amount = np.full(n, mk.notional) if sizes is None else sizes.draw(auc_rng, n)
    return Tape(rate, t0, informed, u, deadline, amount)


def pnl_at_fixed_markup(m: float, window: float, tape: Tape, mk: Market) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """P&L of every quote at markup m (gas at its mean), the mask of quotes whose window was not capped, and who awarded."""
    w = np.minimum(window, tape.deadline - mk.latency - tape.t0)
    r0 = tape.rate[tape.t0.astype(int)]
    t_award = np.where(tape.informed, tape.t0 + w, tape.t0 + tape.u * w)
    awarded = ~tape.informed | (r0 * (1 + m) < tape.rate[(tape.t0 + w).astype(int)])
    x = tape.rate[(t_award + mk.latency).astype(int)] / r0
    held = np.where(awarded, t_award + mk.latency + mk.lock - tape.t0, w)   # capital reserved, then locked
    carry = mk.cost_of_capital * tape.amount * held / SECONDS_PER_YEAR
    return np.where(awarded, tape.amount * (1 - x / (1 + m)) - mk.gas_mean, 0.0) - carry, w >= window, awarded


def breakeven(window: float, mk: Market, seconds: float = 120_000, seed: int = 20261002, batches: int = 60) -> dict:
    """Simulated break-even markup with a 95% CI from batch means over time, and how often the informed exercised."""
    m0 = fair_markup(window, replace(mk, nu=math.inf))
    ms = np.array([m0 - 1e-4, m0, m0 + 1e-4])
    edges = np.linspace(0.0, seconds, batches + 1)
    means = np.zeros((3, batches))
    informed_fills = 0
    for tape in (spec_market(mk, seconds, seed), spec_market(mk, seconds, seed, mirror=True)):
        for i, m in enumerate(ms):
            pnl, ok, awarded = pnl_at_fixed_markup(m, window, tape, mk)
            informed_fills += int(np.sum(tape.informed & awarded & ok)) if i == 1 else 0
            idx = np.searchsorted(tape.t0[ok], edges)
            cum = np.concatenate(([0.0], np.cumsum(pnl[ok])))
            means[i] += (cum[idx[1:]] - cum[idx[:-1]]) / np.diff(idx) / 2
    z = 1.0 / (1.0 + ms)

    def root(y: np.ndarray) -> float:  # zero of the parabola through the three (z, pnl) points
        r = np.roots(np.polyfit(z, y, 2))
        r = r[np.isreal(r)].real
        return 1.0 / r[np.argmin(np.abs(r - z[1]))] - 1.0

    per_batch = np.array([root(means[:, b]) for b in range(batches)])
    ci = stats.t.ppf(0.975, batches - 1) * per_batch.std(ddof=1) / math.sqrt(batches)
    return {"window": window, "sim_bp": root(means.mean(axis=1)) * 1e4, "ci_bp": ci * 1e4,
            "gaussian_bp": m0 * 1e4, "student_bp": fair_markup(window, mk) * 1e4, "informed_fills": informed_fills}


def capacity_run(window: float, mk: Market, capital: float, markup: float, seconds: float = 20_000,
                 seed: int = 20261002, sizes: Optional[Sizes] = None, min_size: float = 0.0,
                 arrival_rate: float = ARRIVAL_RATE) -> dict:
    """Finite capital, event-driven, quoting a fixed markup. Returns realised profit per second, utilisation and the share quoted."""
    tape = spec_market(mk, seconds, seed, sizes=sizes, arrival_rate=arrival_rate)
    inv = Inventory(capital, min_size)
    eng = Engine(mk, window, inv, markup_fn=lambda w: markup)
    settle = mk.latency + mk.lock
    heap: list[tuple[float, int, int]] = []        # (time, 0 release | 1 informed decision | 2 award, quote id)
    profit = in_use_time = last = 0.0
    quoted = 0

    def tick(t: float) -> None:
        nonlocal in_use_time, last
        in_use_time += (inv.reserved + inv.committed) * (t - last)
        last = t

    for i, t0 in enumerate(tape.t0):
        while heap and heap[0][0] <= t0:
            t, kind, qid = heapq.heappop(heap)
            tick(t)
            if kind == 0:
                eng.on_release(qid)
            elif kind == 2 or eng.live[qid].price < tape.rate[int(t)]:
                q = eng.on_award(qid, t)
                x = tape.rate[int(t + mk.latency)] / q.rate
                profit += q.amount * (1 - x / (1 + q.markup)) - mk.gas_mean - mk.cost_of_capital * q.amount * (t + settle - q.quoted_at) / SECONDS_PER_YEAR
                heapq.heappush(heap, (t + settle, 0, qid))
            else:
                q = eng.live[qid]
                profit -= mk.cost_of_capital * q.amount * q.window / SECONDS_PER_YEAR
                eng.on_expiry(qid)
        tick(t0)
        out = eng.on_auction(Auction(i, t0, tape.deadline[i], float(tape.amount[i])), t0, tape.rate[int(t0)])
        if isinstance(out, Quote):
            quoted += 1
            when = out.award_deadline if tape.informed[i] else t0 + tape.u[i] * out.window
            heapq.heappush(heap, (when, 1 if tape.informed[i] else 2, out.id))
    tick(seconds)
    return {"capital": capital, "min_size": min_size, "profit_per_s": profit / seconds,
            "utilisation": in_use_time / (capital * seconds), "accept_share": quoted / len(tape.t0)}
