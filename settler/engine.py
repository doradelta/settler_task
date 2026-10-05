"""Part A: auction events in, quote-or-decline out. In memory, single process.

Lifecycle: on_auction -> Quote | Decline; on_award (reserved -> committed); on_expiry / on_release (freed).

Problem 2 lives in Inventory. A live quote reserves one payment. With penalty = inf no quote is ever
naked (live + committed <= capacity). With a finite penalty F for an award we cannot fund, the policy
overbooks to the newsvendor level: the n-th live quote is allowed while
    p_fill · margin >= F · ΔE_n,
ΔE_n being the extra unfunded award it brings. Uninformed quotes always fill; informed ones watch the same
rate path, so we take the conservative extreme and let them fill together with probability q or not at all:
    ΔE_n = q · 1{n > free} + (1-p)(1-q) · P(Bin(n-1, 1-p) >= free),   p_fill = 1 - p(1-q).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from enum import Enum
from typing import Callable, Optional, Union

from scipy import stats

from .pricing import Market, fair_markup


class Reason(str, Enum):
    INFEASIBLE = "infeasible"        # fulfillment_deadline leaves less than the settlement latency
    NO_INVENTORY = "no_inventory"


@dataclass(frozen=True)
class Auction:
    id: int
    opened_at: float
    fulfillment_deadline: float
    amount: float = 1000.0


@dataclass(frozen=True)
class Quote:
    id: int
    auction_id: int
    quoted_at: float
    rate: float            # R0 observed when quoting
    markup: float
    price: float           # R0 · (1 + markup), source per destination unit
    award_deadline: float  # min(now + W, fulfillment_deadline - latency)
    window: float          # award_deadline - quoted_at


@dataclass(frozen=True)
class Decline:
    auction_id: int
    reason: Reason


@lru_cache(maxsize=None)
def newsvendor_cap(free: int, p_informed: float, q: float, margin: float, penalty: float) -> int:
    """Largest n whose marginal live quote still pays; ΔE_n is non-decreasing, so expected profit is concave in n."""
    p_fill = 1.0 - p_informed * (1.0 - q)
    if not math.isfinite(penalty) or margin <= 0.0 or p_fill == 0.0 or margin >= penalty:
        return free  # no usable penalty: never a naked quote

    def extra_unfunded(n: int) -> float:  # ΔE_n = E[(A_n - free)+] - E[(A_{n-1} - free)+]
        return q * float(n > free) + (1 - p_informed) * (1 - q) * stats.binom.sf(free - 1, n - 1, 1 - p_informed)

    n = free
    while penalty * extra_unfunded(n + 1) <= p_fill * margin:
        n += 1
    return n


@dataclass
class Inventory:
    capacity: Optional[int] = None   # payments we can fund; None = unlimited
    p_informed: float = 0.3          # share of originators who only award when the rate beat the quote
    q_informed: float = 0.0          # P(the rate beats the quote at the deadline): from problem 1
    margin: float = 0.0              # expected profit per fill, source units
    penalty: float = math.inf        # cost of an award we cannot fund; inf = never overbook
    live: int = 0
    committed: int = 0
    overdrafts: int = 0

    @property
    def p_fill(self) -> float:
        return 1.0 - self.p_informed * (1.0 - self.q_informed)

    def max_live(self) -> float:
        if self.capacity is None:
            return math.inf
        return newsvendor_cap(self.capacity - self.committed, self.p_informed, self.q_informed, self.margin, self.penalty)

    def try_reserve(self) -> bool:
        if self.capacity is not None and self.live >= self.max_live():
            return False
        self.live += 1
        return True

    def commit(self) -> None:
        self.live -= 1
        self.committed += 1
        if self.capacity is not None and self.committed > self.capacity:
            self.overdrafts += 1

    def cancel(self) -> None:
        self.live -= 1

    def release(self) -> None:
        self.committed -= 1


class Engine:
    def __init__(self, market: Market, window: float, inventory: Optional[Inventory] = None,
                 markup_fn: Optional[Callable[[float], float]] = None) -> None:
        self.market, self.window = market, window
        self.inventory = inventory or Inventory()
        self._markup_fn = markup_fn or (lambda w: fair_markup(w, market))
        self._cache: dict[float, float] = {}
        self.live: dict[int, Quote] = {}
        self._next_id = 0

    def markup(self, window: float) -> float:
        key = round(window)  # one markup per second of window: rounding moves m* by < 0.001 bp at the spec, < 0.04 bp at σ = 10 bp
        if key not in self._cache:
            self._cache[key] = self._markup_fn(key)
        return self._cache[key]

    def on_auction(self, a: Auction, now: float, rate: float) -> Union[Quote, Decline]:
        latest_safe_bid = a.fulfillment_deadline - self.market.latency
        if latest_safe_bid <= now:
            return Decline(a.id, Reason.INFEASIBLE)
        deadline = min(now + self.window, latest_safe_bid)
        m = self.markup(deadline - now)             # price before reserving: a pricing error leaks no slot
        if not self.inventory.try_reserve():
            return Decline(a.id, Reason.NO_INVENTORY)
        q = Quote(self._next_id, a.id, now, rate, m, rate * (1.0 + m), deadline, deadline - now)
        self.live[q.id] = q
        self._next_id += 1
        return q

    def on_award(self, quote_id: int, now: float) -> Quote:
        q = self.live[quote_id]
        if now > q.award_deadline + 1e-9:
            raise ValueError(f"award after deadline for quote {quote_id}")
        del self.live[quote_id]
        self.inventory.commit()
        return q

    def on_expiry(self, quote_id: int) -> None:
        del self.live[quote_id]
        self.inventory.cancel()

    def on_release(self, quote_id: int) -> None:
        self.inventory.release()
