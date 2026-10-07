# Settler Quote Engine

A firm quote that cannot be withdrawn is an option written for free. This repo prices it, in Rust. The brief is in [Takehome_Settler_Quote_Engine.md](Takehome_Settler_Quote_Engine.md). The required chart is below; an interactive version of the same model, to move the parameters live, is at **[doradelta.github.io/settler_task](https://doradelta.github.io/settler_task/)** (`docs/index.html`).

| File | Part | What it does |
|---|---|---|
| `src/pricing.rs` | B | the fair markup m\*(W) |
| `src/engine.rs` | A | auction in, quote or decline out; only quotes what it can fund |
| `src/sim.rs` | C | runs the engine against the spec's market, break-even with a 95 % CI |
| `src/chart.rs`, `src/main.rs` | C | the table, `results/curve.csv`, `chart/markup_vs_window.svg`, `docs/data.js` |

## Pricing the time in a firm quote

A quote at price Q, held for W seconds, hands the originator a call on the rate: strike = our price, expiry = W, premium zero. The whole model is one balance:

```math
\begin{gathered}
Q = R_0\,(1+m) \\[10pt]
\underbrace{\underbrace{(1-p)}_{70\%}\,\big(\underbrace{M}_{\text{markup}} - \underbrace{G}_{\text{gas}}\big)}_{\text{what the uninformed pay}}
\;=\;
\underbrace{\underbrace{p}_{30\%}\,\big(\underbrace{V}_{\text{option}} + \underbrace{q\,G}_{\text{gas on exercise}}\big)}_{\text{what the informed take}}
\;+\;
\underbrace{C}_{\text{capital}}
\end{gathered}
```

*What we earn from the uninformed pays for what the informed take, plus the capital.*

```
Q = R₀ · (1 + m)                       the price we quote
├── R₀   the market rate now
└── m    our markup: the one that balances the scale
     │
     │   (1 − p)·(M − G)  =  p·(V + q·G)  +  C
     │
     ├── WHAT WE EARN: uninformed originators
     │   ├── 1 − p = 70 %   accept at a random time, whatever the price
     │   ├── M   what we earn per payment at markup m        (N·m/(1+m), N = 1,000)
     │   └── G   average gas per payment                     (12.5, 1.25 %)
     │        └── with only this side: M = G  →  m = 126.6 bp, the gas floor
     │
     └── WHAT WE LOSE
         ├── p = 30 %   informed originators: they only accept when we already lose
         ├── V   the option we give away: how far, on average, the rate overshoots our price
         │   ├── m       how far our price sits from the market (more markup, cheaper option)
         │   ├── σ√W     one normal move over the window (σ = 2 bp/√s, W = 5 s to 5 min)
         │   ├── ν = 4   fat tails (Student-t); ν = ∞ is the spec's Gaussian
         │   └── priced with Bachelier, the short-horizon option formula
         ├── q·G   the gas we pay when the informed exercise (q = probability they do)
         └── C     cost of the capital tied up (10 %/yr, under 0.01 bp)
```

m sits on both sides (it is our income and our strike), so a bisection finds it (`src/pricing.rs`). With the spec's gas V is almost zero: m ≈ 126.6 bp and the window barely matters. With gas ÷ 10, V matters: m rises from 12.5 to 17.2 bp.

<details>
<summary>The closed form behind V and q</summary>

The move over the window is r = c·T with T Student-t(ν) and c = σ√W·√((ν−2)/ν), so its variance is σ²W (a t is a Gaussian whose variance is uncertain). With a = m/c: E[(r − m)⁺] = c·[(ν + a²)/(ν − 1)·f_ν(a) − a·(1 − F_ν(a))], q = 1 − F_ν(a), and V = N/(1+m)·E[(r − m)⁺]. As ν → ∞ this is the Gaussian Bachelier call σ√W·[φ(a) − a·Φ(−a)]. In the code M also carries the spec's small upward drift, 1 + σ²(W/4 + L/2) (0.03 bp at 300 s), and C = 10 %/yr × N × the seconds a payment is reserved, then locked.
</details>

We quote ν = 4 as a placeholder for a tape we have not seen (where minute-scale crypto returns tend to sit); against the spec's Gaussian it over-charges 0.24 bp at 300 s and nothing at 5 s. In production σ would come from an EWMA of the tape, and p, q and ν from **markouts** of quotes (walk-aways plus awards at the deadline give p, their ratio gives q, the depth of the deadline markouts picks ν). For a pinned corridor (stablecoin to stablecoin) the rate mean-reverts: an Ornstein–Uhlenbeck process caps the move at σ/√(2κ) and with it the price of time (a slider on the interactive page).

**The curve.** Lines: the model. Dots: the engine run against the specified Gaussian market, 120,000 s per point, seed 20261002 (each run averaged with its mirror path; gas at its known mean):

![markup vs window](chart/markup_vs_window.svg)

| W | 5 s | 60 s | 300 s |
|---|---|---|---|
| model, Gaussian (bp) | 126.593 | 126.600 | 126.640 |
| model, Student-t ν = 4 (bp) | 126.593 | 126.612 | 126.880 |
| engine on the spec market (bp) | 126.593 ± 0.0002 | 126.600 ± 0.0005 | 126.648 ± 0.033 |

Why it is flat: gas puts our price 126.6 bp above the market while the rate moves 35 bp in five minutes, so the informed originator needs a 3.6σ move and the option is worth 0.01 bp. Of the +0.05 bp from 5 s to 5 min under the Gaussian, 0.030 is the spec's drift (exp(σZ) steps have mean exp(σ²/2)), 0.009 is carry and 0.008 is the option; under t(4) the option alone is 0.25 bp, about 30× the Gaussian figure. The expected markout of an informed fill, V/q, is 8 bp of the payment under the Gaussian and 46 bp under t: the number a desk watches. Divide gas by ten and the strike sits 0.5σ away: the markup climbs 12.5 → 17.2 bp, and there the variance-matched t is *cheaper* (16.6 bp), because matching the variance thins the body to fatten the tail; fat tails cost more only once the strike is past ≈1.2σ for the call itself, ≈1.7σ for the markup once the gas paid on exercise is included. The spec curve starts to bend at W ≈ (ln K / 2σ)² ≈ 16 min, 4 min if σ doubles.

**Stability.** The ± is a 60-batch t-interval; the Gaussian model sits inside it at all 11 gas ÷ 10 points and at spec gas up to 180 s. At spec gas an informed exercise needs a 3.6σ move inside the window, so this run saw none for W ≤ 240 s and 38 at 300 s, nearly all in one batch: those two dots check gas, drift and carry only, and on other seeds the model can fall outside their interval. The option term is checked on the gas ÷ 10 panel (hundreds of exercises at 5 s, thousands from 10 s on). All points share one seed, so their errors are correlated.

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
