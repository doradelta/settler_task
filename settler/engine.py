"""Part A: auction events in, quote-or-decline out. In memory, single process.

Lifecycle: on_auction -> Quote | Decline; on_award (reserved -> committed); on_expiry / on_release (freed).

Concurrency: a live quote reserves its full amount of capital and an award locks it until release, so we
only quote what we can fund (never a naked quote). With 50 live quotes and capital for 10, the 11th is declined.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Union

from .pricing import Market, fair_markup


class Reason(str, Enum):
    INFEASIBLE = "infeasible"    # fulfillment_deadline leaves less than the settlement latency
    NO_CAPITAL = "no_capital"    # every unit of capital is reserved or locked


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
    amount: float          # source units promised
    award_deadline: float  # min(now + W, fulfillment_deadline - latency)
    window: float          # award_deadline - quoted_at


@dataclass(frozen=True)
class Decline:
    auction_id: int
    reason: Reason


@dataclass
class Inventory:
    capital: Optional[float] = None  # source units we can front; None = unlimited
    reserved: float = 0.0
    committed: float = 0.0

    def try_reserve(self, amount: float) -> bool:
        if self.capital is not None and self.reserved + self.committed + amount > self.capital + 1e-9:
            return False
        self.reserved += amount
        return True

    def commit(self, amount: float) -> None:
        self.reserved -= amount
        self.committed += amount

    def cancel(self, amount: float) -> None:
        self.reserved -= amount

    def release(self, amount: float) -> None:
        self.committed -= amount


class Engine:
    def __init__(self, market: Market, window: float, inventory: Optional[Inventory] = None,
                 markup_fn: Optional[Callable[[float], float]] = None) -> None:
        self.market, self.window = market, window
        self.inventory = inventory or Inventory()
        self._markup_fn = markup_fn or (lambda w: fair_markup(w, market))
        self._cache: dict[float, float] = {}
        self.live: dict[int, Quote] = {}
        self.committed: dict[int, Quote] = {}
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
        m = self.markup(deadline - now)             # price before reserving: a pricing error leaks no capital
        if not self.inventory.try_reserve(a.amount):
            return Decline(a.id, Reason.NO_CAPITAL)
        q = Quote(self._next_id, a.id, now, rate, m, rate * (1.0 + m), a.amount, deadline, deadline - now)
        self.live[q.id] = q
        self._next_id += 1
        return q

    def on_award(self, quote_id: int, now: float) -> Quote:
        q = self.live[quote_id]
        if now > q.award_deadline + 1e-9:
            raise ValueError(f"award after deadline for quote {quote_id}")
        del self.live[quote_id]
        self.inventory.commit(q.amount)
        self.committed[quote_id] = q
        return q

    def on_expiry(self, quote_id: int) -> None:
        q = self.live.pop(quote_id)
        self.inventory.cancel(q.amount)

    def on_release(self, quote_id: int) -> None:
        q = self.committed.pop(quote_id)
        self.inventory.release(q.amount)
