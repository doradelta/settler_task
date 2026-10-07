# Settler Quote Engine

A firm quote that cannot be withdrawn is an option written for free. This repo prices it, in Rust. The brief is in [Takehome_Settler_Quote_Engine.md](Takehome_Settler_Quote_Engine.md). The required chart is below; an interactive version of the same model, to move the parameters live, is at **[doradelta.github.io/settler_task](https://doradelta.github.io/settler_task/)** (`docs/index.html`).

| File | Part | What it does |
|---|---|---|
| `src/pricing.rs` | B | the fair markup m\*(W) |
| `src/engine.rs` | A | auction in, quote or decline out; only quotes what it can fund |
| `src/sim.rs` | C | runs the engine against the spec's market, break-even with a 95 % CI |
| `src/chart.rs`, `src/main.rs` | C | the table, `results/curve.csv`, `chart/markup_vs_window.svg`, `docs/data.js` |

## Pricing the time in a firm quote

A quote at price Q, held for W seconds, hands the originator a call on the rate: strike = our price, expiry = W, premium zero. The break-even price, in one equation:

```math
Q^{*} \;=\; \frac{\underbrace{R_0}_{\text{rate now}}}{\,1 \;-\; \underbrace{g}_{\text{gas}} \;-\; \underbrace{\dfrac{p\,\big(v + q\,g\big) + c}{1-p}}_{\substack{\text{what the informed take, plus capital,}\\ \text{paid by the uninformed}}}\,}
```

*Today's rate, grossed up by everything a quote costs us as a share of the payment.*

```
Q* = R₀ / (1 − g − (p·(v + q·g) + c) / (1 − p))        the break-even price
├── R₀    the market rate now
├── g     gas, as a share of the payment                        12.5 / 1,000 = 1.25 %
│         └── on its own: Q* = R₀ / (1 − g) = R₀ · 1.0127, the gas floor (+126.6 bp)
├── p     share of informed originators                         30 %
│         └── divided by 1 − p because only the uninformed (70 %) pay for them
├── v     the option we give away, per unit of payment:
│         how far, on average, the rate ends above our price
│         ├── σ√W   one normal move over the window             σ = 2 bp/√s, W = 5 s to 5 min
│         ├── ν     tail heaviness (Student-t); ∞ is the spec's Gaussian      ν = 4
│         └── priced with Bachelier, the short-horizon option formula
├── q     probability the informed exercise; then we also pay their gas, q·g
└── c     capital tied up while the payment is reserved, then locked     10 %/yr ≈ 0.01 bp
```

v and q are evaluated at Q\* itself (a higher price makes the option cheaper), so `src/pricing.rs` finds Q\* by bisection. With the spec's gas v is almost zero and Q\* stays at the gas floor whatever the window. With gas ÷ 10, v matters: the markup rises from 12.5 to 17.2 bp.

<details>
<summary>The closed form behind v and q</summary>

With m = Q\*/R₀ − 1 the markup, the move over the window is r = c·T with T Student-t(ν) and c = σ√W·√((ν−2)/ν), so its variance is σ²W (a t is a Gaussian whose variance is uncertain). With a = m/c: E[(r − m)⁺] = c·[(ν + a²)/(ν − 1)·f_ν(a) − a·(1 − F_ν(a))], q = 1 − F_ν(a) and v = E[(r − m)⁺]/(1 + m). As ν → ∞ this is the Gaussian Bachelier call σ√W·[φ(a) − a·Φ(−a)]. In the code R₀ also carries the spec's small upward drift, 1 + σ²(W/4 + L/2) (0.03 bp at 300 s).
</details>

We quote ν = 4 as a placeholder for a tape we have not seen (where minute-scale crypto returns tend to sit); against the spec's Gaussian it over-charges 0.24 bp at 300 s and nothing at 5 s. In production σ would come from an EWMA of the tape, and p, q and ν from **markouts** of quotes (walk-aways plus awards at the deadline give p, their ratio gives q, the depth of the deadline markouts picks ν). For a pinned corridor (stablecoin to stablecoin) the rate mean-reverts: an Ornstein–Uhlenbeck process caps the move at σ/√(2κ) and with it the price of time (a slider on the interactive page).

**The curve.** Lines: the model. Dots: the engine run against the specified Gaussian market, 120,000 s per point, seed 20261002 (each run averaged with its mirror path; gas at its known mean):

![markup vs window](chart/markup_vs_window.svg)

| W | 5 s | 60 s | 300 s |
|---|---|---|---|
| model, Gaussian (bp) | 126.593 | 126.600 | 126.640 |
| model, Student-t ν = 4 (bp) | 126.593 | 126.612 | 126.880 |
| engine on the spec market (bp) | 126.593 ± 0.0002 | 126.600 ± 0.0005 | 126.648 ± 0.033 |

Why it is flat: gas puts our price 126.6 bp above the market while the rate moves 35 bp in five minutes, so the informed originator needs a 3.6σ move and the option is worth 0.01 bp. Of the +0.05 bp from 5 s to 5 min under the Gaussian, 0.030 is the spec's drift (exp(σZ) steps have mean exp(σ²/2)), 0.009 is carry and 0.008 is the option; under t(4) the option alone is 0.25 bp, about 30× the Gaussian figure. The expected markout of an informed fill, v/q, is 8 bp of the payment under the Gaussian and 46 bp under t: the number a desk watches. Divide gas by ten and the strike sits 0.5σ away: the markup climbs 12.5 → 17.2 bp, and there the variance-matched t is *cheaper* (16.6 bp), because matching the variance thins the body to fatten the tail; fat tails cost more only once the strike is past ≈1.2σ for the call itself, ≈1.7σ for the markup once the gas paid on exercise is included. The spec curve starts to bend at W ≈ (ln K / 2σ)² ≈ 16 min, 4 min if σ doubles.

**Stability.** The ± is a 60-batch t-interval; the Gaussian model sits inside it at all 11 gas ÷ 10 points and at spec gas up to 180 s. At spec gas an informed exercise needs a 3.6σ move inside the window, so this run saw none for W ≤ 240 s and 38 at 300 s, nearly all in one batch: those two dots check gas, drift and carry only, and on other seeds the model can fall outside their interval. The option term is checked on the gas ÷ 10 panel (hundreds of exercises at 5 s, thousands from 10 s on). All points share one seed, so their errors are correlated.

## Beyond break-even: hedging, alone or competing

Q\* is the price at which we neither win nor lose on average. What we actually quote adds a margin, and how much depends on whether we are alone or competing. Profit comes first: we are competitive only while it pays.

```math
Q \;=\; \max\!\Big(\underbrace{Q^{*}\big(1 + z\,\frac{\sigma_{\text{fill}}}{\sqrt{n}}\big)}_{\text{floor}},\;\; \min\!\big(\underbrace{Q^{*}\,(1 + 1/\beta)}_{\text{alone}},\; \underbrace{Q_{\text{rival}} - \varepsilon}_{\text{competing}}\big)\Big)
```

```
Q = max( floor , min( alone , competing ) )                the price we actually quote
├── floor = Q*·(1 + z·σ_fill/√n)     never below: break-even plus a safety margin
│   ├── Q*        the break-even price above
│   ├── σ_fill    noise per fill once the rate is hedged, as a share of the payment
│   │             ≈ 0.43 %, almost all of it gas (uniform 5 to 20 units)
│   ├── n         fills per day                     ≈ 5,000 with capital for 10 payments
│   └── z         confidence                        2.33 → 99 % of days profitable
│                 └── together: about +1.4 bp above Q*
├── alone = Q*·(1 + 1/β)             no rival: as high as demand allows
│   └── β         share of fills lost per extra bp of markup (measured from fill rates)
│                 └── e.g. 5 % per bp → +20 bp
└── competing = Q_rival − ε          one tick under the best rival
    └── when that is below the floor, the floor wins and we let the rival take the auction
```

- **Alone:** there is no rival (Q_rival = ∞), so Q = Q\*·(1 + 1/β). In the spec the uninformed ignore the price, so a lone settler could raise it without limit; in practice β is measured.
- **Competing:** Q = max(floor, Q_rival − ε): one tick under the rival, as long as that still clears the floor.

**Hedging.** When quoting, buy the destination units we expect to deliver: all of the uninformed's and a fraction q of the informed's, raising that fraction as the rate approaches our price. When the award comes, the hedge becomes the delivery. That removes the rate risk every live quote shares, which does not diversify; what is left (gas, who shows up) diversifies over n fills, which is why the floor is only about 1.4 bp above Q\*. Hedging does not remove the option's cost: buying all the units upfront turns the short call into a short put whenever the informed walk away (put–call parity), so Q\* stays the floor.

This section is not simulated (the specified market has no rivals and price-blind uninformed demand), and its numbers are orders of magnitude: σ_fill is the spread of the uniform gas, and n comes from 0.058 fills per second with capital for 10 payments.

## Concurrency (Part A)

A live quote reserves its full payment of capital and an award keeps it locked until release, so the engine only quotes what it can fund: with capital for 10 payments and 50 auctions, auctions 11 to 50 are declined (a test in `src/engine.rs`). No quote is ever naked; with one payment size and one corridor there is nothing further to optimise until the protocol publishes a penalty for unfunded awards (then overbooking against the walk-away rate, see Notes). The window still matters here: a longer window keeps capital reserved longer, so the same capital completes fewer payments per second.

## Run

    cargo test --release     # 11 tests
    cargo run --release      # prints the table, writes results/, chart/ and docs/data.js (about 4 s)

## Notes

- **Instrument:** markouts of awarded quotes by time-to-award (walk-aways plus the deadline spike give p, their ratio q), realised σ, and realised break-even minus quoted markup with a CI.
- **Polygon vs Solana:** same price (carry < 0.02 bp on either chain) but 256 s vs 13 s of locked capital: at W = 60 s (L = 2 blocks on each chain) the same corridor turns inventory 4.5× slower on Polygon, and if rebalancing happens at release the rate variance over the lock is 20× larger.
- **Missing from the protocol:** cancel or re-price a live quote (kills the option), a published penalty for failed fulfilment (prices overbooking), originator identity (p per counterparty).
- **With more time:** overbooking against the walk-away rate once the protocol publishes a penalty for unfunded awards; importance-sample the informed tail so the spec-gas option is checked at 300 s instead of waiting for a rare cluster.

## Assumptions

Student-t(ν = 4) for the quote, the spec's Gaussian process (uncorrected log steps, +0.035 bp at 300 s) for the simulation. Ethereum: L = 2 blocks (24 s), lock = 12 blocks (144 s). Cost of capital 10 %/yr. Fulfilment deadlines U(0, 1 h) ahead, since the spec gives none. Risk-neutral settler, price-inelastic uninformed demand, one corridor.
