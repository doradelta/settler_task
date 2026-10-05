# Settler Quote Engine

A firm quote that cannot be withdrawn is an option written for free. This repo prices it, and decides which auctions to quote when capital is finite and payments differ in size. The brief is in [Takehome_Settler_Quote_Engine.md](Takehome_Settler_Quote_Engine.md); every chart below is interactive at **[doradelta.github.io/settler_task](https://doradelta.github.io/settler_task/)** (`docs/index.html`, no build step).

We read the brief as two different problems and keep each to its simplest correct form.

## 1 · Pricing the time in a firm quote

A quote at price Q = R₀(1+m), held for W seconds, hands the originator a call on the rate: strike K = 1+m, expiry W, premium zero. On a fill we earn N·(1 − X/K) − gas, with X = R_exec / R₀.

- **Uninformed originators (70 %)** award at a random time whatever the price, so E[X] ≈ 1 and they only need to pay for gas: m_G = Ḡ / (N − Ḡ) = **126.6 bp** (the spec's gas is 1.25 % of a payment).
- **Informed originators (30 %)** award only if the rate beat our price: a short call. We give the return r a standard deviation σ√W and a **Student-t shape** with ν degrees of freedom, variance-matched (a t is a Gaussian whose variance is uncertain; ν says how well we know σ over the window, and ν = ∞ is the Gaussian the spec simulates):

  E[loss] = (N/K)·E[(r − m)⁺] + Ḡ·P(r > m), E[(r − m)⁺] = c·[(ν + a²)/(ν − 1)·f_ν(a) − a·(1 − F_ν(a))], a = m/c, c = σ√W·√((ν−2)/ν).

- **Break-even:** (1−p)·E[profit | uninformed] + p·E[profit | informed] − carry = 0, where carry is the cost of capital while the payment is reserved, then locked. m is both the revenue and the strike, so this is a fixed point; it is monotone in m, so one bisection solves it (`settler/pricing.py`).

For a pinned corridor (stablecoin to stablecoin) the rate mean-reverts instead of wandering; that only replaces σ²W by σ²(1 − e^(−2κW))/2κ (`Market.mean_reversion`, an OU process) and caps the price of time at the reversion horizon. The spec's market is a random walk, κ = 0, and so is everything below.

We quote ν = 4 as a placeholder for a tape we have not seen (finite variance, infinite kurtosis, where minute-scale crypto returns tend to sit); against the spec's Gaussian it over-charges 0.24 bp at 300 s and nothing at 5 s. What a desk adds on top: σ from an EWMA of the tape (`realized_sigma`, written, not needed by the spec run); p, q and ν from **markouts** of quotes (walk-aways plus awards at the deadline give p, their ratio gives q, the depth of the deadline markouts picks ν); the tail stays in closed form, no Monte Carlo at quote time.

**The curve.** Lines: the model. Dots: the engine's quote rule run against the specified Gaussian market, 120,000 s per point, seed 20261002 (vectorised, identical to the event loop; antithetic paths; gas at its known mean):

![markup vs window](chart/markup_vs_window.png)

| W | 5 s | 60 s | 300 s |
|---|---|---|---|
| model, Gaussian (bp) | 126.593 | 126.600 | 126.640 |
| model, Student-t ν = 4 (bp) | 126.593 | 126.612 | 126.880 |
| quote rule on the spec market (bp) | 126.593 ± 0.000 | 126.601 ± 0.001 | 126.659 ± 0.028 |

Why it is flat: gas puts our price 126.6 bp above the market while the rate moves 35 bp in five minutes, so the informed originator needs a 3.6σ move and the option is worth 0.01 bp. Of the +0.05 bp from 5 s to 5 min under the Gaussian, 0.03 is the spec's drift (exp(σZ) steps have mean exp(σ²/2)), 0.005 is carry and 0.012 is the option; under t(4) the option alone is 0.25 bp, 20× the Gaussian figure. The expected markout of an informed fill, C/q, is 8 bp under the Gaussian and 46 bp under t: the number a desk watches. Divide gas by ten and the strike sits 0.5σ away: the premium over the floor climbs 0.03 → 4.7 bp, explosively while the strike is still 2–3σ out and about like W^0.65 after a minute, and there the variance-matched t is *cheaper* (16.6 vs 17.2 bp), because matching the variance thins the body to fatten the tail; fat tails cost more only once the strike is past ≈1.15σ for the call itself, ≈1.5σ with the gas paid on exercise. The spec curve starts to bend at W ≈ (ln K / 2σ)² ≈ 16 min, 4 min if σ doubles.

**Stability.** The ± is a 60-batch t-interval; below 2 min it is a true 95 % CI and the Gaussian model sits inside it at every point. At spec gas an informed exercise needs a 3.6σ move inside a 300 s window, so the run saw none for W ≤ 240 s and 55 at W = 300 s, all on one path in three batches: that panel verifies gas, drift and carry, and its 300 s interval is indicative (across 30 seeds the point moves ±0.014 bp around the model). The option term is verified on the gas ÷ 10 panel, where every point has thousands of exercises and coverage is nominal.

## 2 · Finite capital, payments of different sizes

The brief fixes payments at 1,000. With one size and one corridor the inventory question has no decision in it: quote first-come up to capacity, never naked (the brief's "50 live quotes, inventory for 10"). It becomes a decision once sizes vary, so here they are lognormal around 1,000 (`Sizes`), capital is C source units, and we quote a market-set markup of 150 bp with a 1-minute window.

Gas is a fixed cost per fill, so a quote of size a earns **π(a) = α·a − β** in expectation (`profit_line`; at 150 bp payments under 846 units lose money) and ties up **a·T** of capital-time, T being the seconds a payment stays reserved, then locked (157 s). Choosing which auctions to quote is a fractional knapsack:

  maximise Σ x(a)·π(a)  subject to  Σ x(a)·a·T ≤ C,  0 ≤ x(a) ≤ λ·f(a).

Its solution is greedy by yield π(a)/(a·T), which rises with size, so the optimal policy is a **threshold: quote iff a ≥ a_min**, where a_min is the gas break-even size while capital is slack and otherwise the size at which demand just fills the capital. The LP's dual **λ\* is the bid price**: what every unit of capital must earn per second (Talluri–van Ryzin bid-price control; `bid_price`, 30 lines, closed form via the lognormal partial mean). Is it convex? Yes, it is an LP, and the threshold is its closed-form solution; the fluid relaxation is an upper bound that becomes exact once capital is large next to a payment. The dynamic version (react to the capital free right now) is an MDP whose value is concave in capital, which is why one bid price is near-optimal.

Engine runs of 20,000 s, payments drawn from the same distribution, profit per hour in source units:

| capital | quote sizes ≥ | bid price (bp/h) | threshold, fluid | threshold, engine | quote everything you can fund |
|---|---|---|---|---|---|
| 10,000 | 7,554 | 2,112 | 2,142 | 942 | −2,417 |
| 50,000 | 4,935 | 1,970 | 10,440 | 7,302 | −3,874 |
| 200,000 | 2,040 | 1,392 | 35,810 | 31,834 | 7,664 |
| 500,000 | 846 | 0 | 49,793 | 50,099 | 39,871 |

Two things to read off it. Quoting everything you can fund *loses money* while capital is scarce: the payments that still fit when capital is nearly full are the small ones, and those do not cover gas; selecting by size turns that into a profit at every capital level. And the fluid line overstates the engine at small capital (packing: a 7,500 quote on 10,000 of capital blocks everything else), converging above ~200,000.

The window enters through T: a longer window keeps capital reserved longer, which raises the bid price and the threshold. For a 5 bp desk margin that is worth about 13 bp at a 5-minute window against 5 bp at 5 seconds, two orders of magnitude above the option in §1.

## Run

    pip install -r requirements.txt      # Python 3.9+, numpy, scipy, matplotlib, pytest
    python3 -m pytest -q                 # 13 tests, under a second
    python3 run.py                       # results/, docs/data.js, chart/  (about 40 s)

## Notes

- **Instrument:** markouts of awarded quotes by time-to-award (walk-aways plus the deadline spike give p, their ratio q), realised σ against the EWMA, and realised break-even minus quoted markup with a CI.
- **Polygon vs Solana:** same price (carry < 0.02 bp on either chain) but 256 s vs 13 s of locked capital: at W = 60 s the same corridor turns inventory 4.5× slower on Polygon (14× at 5 s, under 2× at 5 min, where the window itself dominates the cycle), and if rebalancing happens at release the rate variance over the lock is 20× larger.
- **Missing from the protocol:** cancel or re-price a live quote (kills the option), a published penalty for failed fulfilment (prices overbooking), originator identity (p per counterparty).
- **With more time:** a packing-aware version of the threshold for small capital (the fluid LP is 2× optimistic at 10,000); overbooking against the walk-away rate once the protocol publishes a penalty for unfunded awards (a newsvendor fractile, with informed originators exercising together); importance-sample the informed tail so the spec-gas option is verified at 300 s instead of waiting for a rare cluster.

## Assumptions

Student-t(ν = 4) for the quote, the spec's Gaussian process (uncorrected log steps, +0.035 bp at 300 s) for the simulation. Ethereum: L = 2 blocks (24 s), lock = 12 blocks (144 s). Cost of capital 10 %/yr. Fulfilment deadlines U(0, 1 h) ahead, since the spec gives none. Payment sizes lognormal(1,000, 0.8) in §2 only; capital is divisible in the fluid model, whole in the engine. Risk-neutral settler, price-inelastic uninformed demand, one corridor.
