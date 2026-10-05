import math

import numpy as np
import pytest
from scipy import integrate, stats

from settler import (Auction, Decline, Engine, Inventory, Market, Quote, breakeven, fair_markup, gas_floor,
                     realized_sigma, tail_call, window_std)
from settler.simulate import pnl_at_fixed_markup, spec_market

MK = Market()


@pytest.mark.parametrize("nu,k", [(3.0, 0.5), (4.0, 2.0), (4.0, 5.0), (math.inf, 1.0)])
def test_tail_call_matches_numerical_integral(nu, k):
    s = 1.0
    c = s if math.isinf(nu) else s * math.sqrt((nu - 2) / nu)
    pdf = (lambda r: stats.norm.pdf(r)) if math.isinf(nu) else (lambda r: stats.t.pdf(r / c, nu) / c)
    call, q = tail_call(k, s, nu)
    assert call == pytest.approx(integrate.quad(lambda r: (r - k) * pdf(r), k, np.inf)[0], rel=1e-8)
    assert q == pytest.approx(integrate.quad(pdf, k, np.inf)[0], rel=1e-8)


def test_fair_markup_limits():
    free = Market(cost_of_capital=0.0)
    assert fair_markup(300, Market(**{**free.__dict__, "sigma": 0.0})) == pytest.approx(gas_floor(MK), abs=1e-9)       # no rate risk
    drift = 1 + MK.sigma**2 * (300 / 4 + MK.latency / 2)                                                              # nobody picks us off:
    assert fair_markup(300, Market(**{**free.__dict__, "p_informed": 0.0})) == pytest.approx(MK.notional * drift / (MK.notional - MK.gas_mean) - 1, abs=1e-9)
    windows = [5, 30, 60, 120, 300, 1200, 3600]
    assert all(np.diff([fair_markup(w, MK) for w in windows]) > 0)                            # time costs money
    assert fair_markup(300, Market(nu=1e9)) == pytest.approx(fair_markup(300, Market(nu=math.inf)), rel=1e-6)


def test_mean_reversion_caps_the_price_of_time():
    ou = Market(mean_reversion=math.log(2) / 60)                                  # one-minute half-life
    assert window_std(5, ou) == pytest.approx(window_std(5, MK), rel=0.03)         # short windows: a random walk
    assert window_std(3600, ou) == pytest.approx(window_std(600, ou), rel=1e-6)    # long windows: saturated at σ/√(2κ)
    assert fair_markup(300, ou) < fair_markup(300, MK)


def test_engine_feasibility_capping_and_capital_reservation():
    eng = Engine(MK, window=300.0, inventory=Inventory(capital=2000.0))
    assert isinstance(eng.on_auction(Auction(0, 0.0, 20.0), 0.0, 1.0), Decline)   # 20 s left < 24 s latency
    q = eng.on_auction(Auction(2, 0.0, 100.0), 0.0, 1.0)
    assert isinstance(q, Quote) and q.award_deadline == 76.0 and q.markup < eng.markup(300.0)
    assert isinstance(eng.on_auction(Auction(3, 1.0, 4000.0), 1.0, 1.0), Quote)
    assert eng.on_auction(Auction(4, 2.0, 4000.0, amount=500.0), 2.0, 1.0).reason.value == "no_capital"
    eng.on_award(q.id, 50.0)
    assert eng.inventory.committed == 1000.0 and isinstance(eng.on_auction(Auction(5, 3.0, 4000.0), 3.0, 1.0), Decline)
    eng.on_release(q.id)
    assert isinstance(eng.on_auction(Auction(6, 4.0, 4000.0), 4.0, 1.0), Quote)


def test_vectorised_quote_rule_is_the_engine():
    tape, m, window = spec_market(MK, 3000, seed=7), 0.0127, 120.0
    _, _, awarded = pnl_at_fixed_markup(m, window, tape, MK)
    eng = Engine(MK, window, Inventory(), markup_fn=lambda w: m)
    for i, t0 in enumerate(tape.t0):
        out = eng.on_auction(Auction(i, t0, tape.deadline[i]), t0, tape.rate[int(t0)])
        latest = tape.deadline[i] - MK.latency
        assert isinstance(out, Quote) == (latest > t0)
        if isinstance(out, Quote):
            assert out.window == pytest.approx(min(window, latest - t0)) and out.price == pytest.approx(tape.rate[int(t0)] * (1 + m))
            assert awarded[i] == ((out.price < tape.rate[int(out.award_deadline)]) if tape.informed[i] else True)


def test_realized_sigma_recovers_a_constant():
    assert realized_sigma(np.full(2000, 2e-4)) == pytest.approx(2e-4)


def test_simulated_breakeven_brackets_the_gaussian_model():
    r = breakeven(60.0, MK, seconds=40_000, batches=20)
    assert abs(r["sim_bp"] - r["gaussian_bp"]) < 3 * r["ci_bp"] + 1e-3
