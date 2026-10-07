# Settler Quote Engine

A firm quote that cannot be withdrawn is an option given away for free. This repo prices it, in Rust. The brief is in [Takehome_Settler_Quote_Engine.md](Takehome_Settler_Quote_Engine.md). The required chart is below; an interactive version of the same model, to move the parameters live, is at **[doradelta.github.io/settler_task](https://doradelta.github.io/settler_task/)** (`docs/index.html`).

| File | Part | What it does |
|---|---|---|
| `src/pricing.rs` | B | the break-even price for a quote held W seconds |
| `src/engine.rs` | A | auction in, quote or decline out; only quotes what it can fund |
| `src/sim.rs` | C | runs the engine against the brief's market and measures where it breaks even |
| `src/chart.rs`, `src/main.rs` | C | the table, `results/curve.csv`, the chart and `docs/data.js` |

## Pricing the time in a firm quote

When we quote, we promise a price for W seconds and the originator decides whether to take it. That is a call option on the exchange rate: the strike is our price, it expires when the window closes, and nobody pays us for it. Seven in ten originators accept at a random moment without looking at the market. Three in ten wait and accept only if the market has moved past our price, which is exactly when we lose. The break-even price:

```math
Q^{*} \;=\; \frac{\underbrace{R_0}_{\text{rate now}}}{\,1 \;-\; \underbrace{g}_{\text{gas}} \;-\; \underbrace{\dfrac{p\,\big(v + q\,g\big) + c}{1-p}}_{\substack{\text{what the informed take, plus capital,}\\ \text{paid by the uninformed}}}\,}
```

*Today's rate, marked up by everything a quote costs us, as a share of the payment.*

```
Q*   the break-even price: the lowest quote that does not lose money on average
├── R₀   the market rate when we quote
├── g    gas, the fee we pay on every delivery: 1.25 % of the payment
│        on its own it sets a floor of 126.6 bp above the market
├── p    the share of informed originators: 30 %
│        their losses are spread over the other 70 %, the ones who actually pay us
├── v    the option we give away: how far, on average, the rate ends above our price
│        it grows with volatility (2 bp per second) and with the window (5 s to 5 min),
│        allows for fat tails (large moves happen more often than a bell curve says)
│        and is priced with Bachelier, the standard formula for very short options
├── q    the chance that an informed originator takes the quote;
│        when they do, we also pay the gas
└── c    the cost of the money we tie up until we are paid back: about 0.01 bp
```

The option and that chance both depend on our own price (a higher price makes the option cheaper), so the code finds the break-even price by trial and error (`src/pricing.rs`).

<details>
<summary>The exact formula behind v and q, for the curious</summary>

With m = Q\*/R₀ − 1 the markup, the move over the window is r = c·T with T Student-t(ν) and c = σ√W·√((ν−2)/ν), so its variance is σ²W. With a = m/c: E[(r − m)⁺] = c·[(ν + a²)/(ν − 1)·f_ν(a) − a·(1 − F_ν(a))], q = 1 − F_ν(a) and v = E[(r − m)⁺]/(1 + m). As ν → ∞ this is the Gaussian Bachelier call. In the code R₀ also carries the brief's small upward drift (0.03 bp at 300 s).
</details>

We use fat tails as a placeholder for a market we have not seen; against the brief's bell-curve market they over-charge by 0.24 bp at 5 minutes and by nothing at 5 seconds. In production the volatility would be measured live, and the share of informed originators estimated from which quotes get taken at the last second. On a stablecoin corridor, where the rate barely moves and is pulled back, the window would cost almost nothing (there is a slider for this on the interactive page).

**The curve.** Lines: what the model says. Dots: what the engine actually earns when run against the brief's market (120,000 simulated seconds per point, seed 20261002).

![markup vs window](chart/markup_vs_window.svg)

| Window | 5 s | 60 s | 300 s |
|---|---|---|---|
| model, bell curve (bp) | 126.593 | 126.600 | 126.640 |
| model, fat tails (bp) | 126.593 | 126.612 | 126.880 |
| engine on the brief's market (bp) | 126.593 ± 0.0002 | 126.600 ± 0.0005 | 126.648 ± 0.033 |

Why it is flat: the brief's gas forces a 126.6 bp markup, which puts our price far above where the rate can realistically go in five minutes (about 35 bp). The informed originator almost never finds the quote worth taking, so a 5-minute window adds only 0.05 bp, and most of that is not the option but a small upward drift built into the brief's rate. With fat tails the option is worth a little more: 0.25 bp at 5 minutes. With gas ten times cheaper our price sits close to the market and the window costs real money: from 12.5 bp at 5 seconds to 17.2 bp at 5 minutes. At the brief's gas the curve would only start bending upward at windows of about 16 minutes, or 4 minutes if volatility doubled.

**How we know the numbers hold.** The engine's dots match the model at every window, within their error bars. At the brief's gas the informed almost never take a quote (not once below 4 minutes in this run), so those dots mostly check the gas and the drift; the cheap-gas panel, where they take quotes thousands of times, checks the option itself.

## Beyond break-even: alone or competing

Break-even is an average. Any single fill can still lose: between the quote and the moment we exchange the units, the rate can move by more than our markup. So we add a cushion on top of Q\*, and its size depends on whether anyone else is quoting. Profit comes first: we are competitive only while it pays.

**Alone.** Nobody undercuts us, so we can protect every fill. The cushion is the biggest move we are prepared to absorb.

```math
Q_{\text{alone}} \;=\; Q^{*}\,\big(1 + z\,\sigma\sqrt{T}\,\big)
```

*Break-even, plus the move the rate can make while we are exposed, times how sure we want to be.*

```
Q_alone   the price we quote when we are the only settler
├── Q*   the break-even price above
├── z    how sure we want to be: 2.3 wins 99 fills in 100 with a bell curve, 2.7 with fat tails
├── σ    how much the rate moves, per √second: 2 bp in the brief
└── T    seconds a fill is exposed: the window, plus the 24 s delivery if we did not hedge at award
```

With the brief's numbers the cushion is 25 bp for a 5 s window and 83 bp for 5 min. Alone we could charge more, up to what customers bear; this is the least that makes the settler win.

**Competing.** The customer takes the best price, so a cushion on every fill would lose nearly every auction. We protect the day instead: over the day's n independent fills the moves average out, so the same cushion is shared by n. Then we go one tick under the best rival, and never below that floor.

```math
Q_{\text{comp}} \;=\; \max\!\Big(\,Q^{*}\big(1 + z\,\sigma\sqrt{T/n}\,\big),\;\; Q_{\text{rival}} - \varepsilon\Big)
```

*Just under the best rival, never below break-even plus the day's cushion.*

```
Q_comp   the price we quote against rivals
├── z, σ, T   as above
├── n         independent price moves in a day: fills open at the same time share one move,
│             so about a day divided by T (270 for a 5 min window, 3,000 for 5 s)
├── Q_rival   the best price anyone else is quoting
└── ε         one price tick: the least that still beats the rival
```

With the brief's numbers the floor is 0.5 bp above break-even for 5 s and 5 bp for 5 min. When the rival is below our floor we quote the floor and lose that auction on purpose.

Gas varies too (5 to 20 per fill), but it does not move with the market and in production we read it off the chain when we quote, so the cushion is about the rate alone: a rate move is unknown in advance and hits every open quote at once.

**Hedging.** We hedge a quote the moment it is awarded, with a perpetual future (long the coin we have to buy, short the one we have to sell), and close the hedge when we exchange the units. That locks the rate from award to delivery and takes the 24 s out of T. We do not hedge at quote time: against rivals most quotes are lost, and even alone three in ten are never taken, so hedging each one would cost more in fees than the risk it removes; the window stays in T and the cushion pays for it. Only when many long quotes are open at once do we hedge their net sum, in bands. Hedging makes results steadier; it does not make money, and it cannot remove the option: a hedge placed at quote time loses exactly when the informed walk away.

This section is not simulated (the brief's market has no rivals, and its uninformed originators ignore the price); its numbers are rough orders of magnitude.

## Concurrency (Part A)

Every open quote sets aside its full payment, and an accepted one stays set aside until we are paid back, so the engine only quotes what it can fund: with money for 10 payments and 50 auctions, auctions 11 to 50 are declined (a test in `src/engine.rs`). We never promise money we do not have. With one payment size there is nothing more to optimise unless the protocol puts a price on failing to pay; then we could safely quote a little more than we can fund, since about 30 % of quotes are never taken. The window still matters here: a longer window keeps money set aside longer, so the same money completes fewer payments per second.

## Run

    cargo test --release     # 11 tests
    cargo run --release      # prints the table, writes results/, chart/ and docs/data.js (about 4 s)

## Notes

- **What to monitor in production:** for every accepted quote, how far the rate moved against us afterwards, split by when it was taken. Quotes taken at the last second are the informed ones, which tells us their share. Also live volatility, and whether we really break even where the model says.
- **Polygon vs Solana:** the same price, but Polygon keeps our money locked about 4 minutes after each payment and Solana about 13 seconds, so with a one-minute window the same money completes about 4.5 times fewer payments on Polygon.
- **Missing from the protocol:** cancelling or re-pricing a live quote (it would remove the option altogether), a published penalty for failed payments (it would let us safely quote more than we can fund), and originator identity (it would let us spot the informed).
- **With more time:** quote above capacity once a penalty exists, and simulate rare large moves more efficiently, so the 5-minute point at the brief's gas is checked properly.

## Assumptions

For pricing, fat-tailed moves (Student-t, ν = 4); for the simulation, the brief's own bell-curve rate. Ethereum timings: 24 s to deliver, 144 s until we are paid back. Money costs 10 % a year. Each auction's hard deadline is up to an hour away (the brief gives none). The settler is risk-neutral, uninformed originators ignore the price, one corridor.
