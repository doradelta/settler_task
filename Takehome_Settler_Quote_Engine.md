# Atum Take-Home: Settler Quote Engine

**Deliverable ceiling: a small repo, one chart, two pages of writing.** That ceiling is the
budget — see *Scope* for what we've deliberately cut to hold it. There is a review call about
this work afterward; details at the end.

## Context: what a settler does

Atum is a payments network. An originator wants to move value from a source chain to a
destination chain. **Settlers** compete to fulfill that payment, and a settler's economics work
like this:

1. An auction opens for a payment request. You decide whether to quote, and at what price.
2. You sign a **firm** quote. The originator may accept it at any point until your quote's
   deadline — or never. You do not choose who wins.
3. If awarded, source funds move into escrow, and then **you front your own capital on the
   destination chain** to pay the recipient.
4. You present proof of fulfillment and only then withdraw the source funds from escrow.

Between step 2 and step 4 you are exposed, in two distinct ways. Making those two exposures
legible — and priced — is the whole exercise.

### Three deadlines, which must not be confused

| Deadline | Owner | Meaning |
|---|---|---|
| `quote_deadline` | gateway | When the auction's collection window closes. You bid before it. |
| `award_deadline` | **you**, signed per quote | The latest moment the originator may award this quote — i.e. how long you hold your price. |
| `fulfillment_deadline` | protocol | The hard on-chain horizon. Miss it and the payment is cancelled and refunded. |

Our production agent computes:

```
award_deadline  = min(now + quote_risk_window, latest_safe_bid_at)
latest_safe_bid_at = fulfillment_deadline − min_settlement_time
```

`quote_risk_window` is today a **static configuration constant**. The markup our agent charges
does not depend on it. That is the gap this exercise is about.

### Where your capital sits

After an award, settlement runs `deposit → fulfill → release`. The step from `fulfill` to
`release` is gated on the **destination** chain reaching a confirmation depth — deep enough that
a reorg can't un-mine the fulfillment you're about to get paid for. Use these:

| Chain | Depth before release |
|---|---|
| Ethereum | 12 blocks |
| Polygon | 128 blocks |
| Tron | 19 blocks |
| Solana | `finalized` commitment |

Deeper is safer and slower; shallower is faster and more reorg-exposed. Your capital is
unavailable for the whole window.

## The Problem

**A firm quote you cannot withdraw is an option you wrote for free.**

You name a price and hold it until `award_deadline`. The originator exercises when it suits
them and walks when it doesn't. Lengthen the window and you have given away a more valuable
option for the same markup. Our five production pricing strategies key on amount and corridor
only — none of them price time.

Your job is to fix that, and to show your work.

## What to Build

### Part A — The engine

A function, not a service: auction events in, quote-or-decline decisions out. In memory, single
process.

It must handle:

- **Feasibility.** Decline when `fulfillment_deadline` leaves less time than settlement needs.
- **Concurrent exposure.** Quotes are firm and outstanding simultaneously. With inventory for
  10 payments and 50 live quotes, you can be awarded on all 50. Your policy for this is a
  decision we want to see you make.

### Part B — The pricing model

About a page. Derive the quote price, treating the firm quote as the short option it is. We
expect you to account for the hold window, for the fact that you are selected against, and for
the cost of capital locked from fulfill to release. Show the reasoning, not just a formula.

### Part C — The curve

**One chart: markup versus risk window, from 5 seconds to 5 minutes**, produced by running your
engine against the market and originator specified below.

That curve is the primary artifact. Everything else supports it.

### Part D — Notes

About a page:

- What you would instrument in production to know whether the model is working.
- What the confirmation table above implies — the same corridor on Polygon versus Solana.
- What the protocol doesn't give you that your model wants.

## The specified market and originator

Implement exactly this. It is deliberately not yours to choose: we want your numbers comparable
to other candidates', and a model shouldn't be graded against an adversary its author tuned.

**The rate.** Track one quantity `R(t)`: the cost, in source-chain units, of acquiring one
destination-chain unit — your rebalancing rate. Start at `R(0) = 1.0`. Step it every second:

```
R(t+1) = R(t) · exp(σ · Z),  Z ~ N(0,1)
```

with `σ = 2` basis points per second. Seed your RNG and state the seed.

**Gas.** Each fulfillment costs you `G` source-chain units, drawn fresh at execution time,
uniform on `[0.5, 2.0]` as a percentage of a 1,000-unit payment. You learn `G` only when you
execute, not when you quote.

**The originator.** For each auction, with probability `p = 0.3` the originator is **informed**
and otherwise **uninformed**.

- *Informed:* waits until the last instant before `award_deadline`, then awards your quote if
  and only if it is better than the prevailing rate `R` at that moment. Otherwise walks.
- *Uninformed:* awards at a uniformly random time within the window, regardless of price.

**Payments.** 1,000 source units each, one corridor, auctions arriving as a Poisson process at
2 per second. Run long enough that your curve is stable; say how you decided it was.

## Scope

**Do not build.** We will discuss these rather than read them:

- Any network transport, API, database, or message bus
- Multi-asset or multi-corridor support — one corridor is enough
- Historical data, calibration to real markets, or parameter fitting
- A UI, a dashboard, or more than the one required chart
- Retries, crash recovery, or operational concerns of any kind

**Yours to choose.** Language and runtime (mixing is fine and expected — an engine in one
language and the analysis in another is a perfectly good answer), numerical approach, project
layout, whether to use a library or roll it yourself, and how much test coverage the work
deserves. We have opinions about none of it.

## What We're Evaluating

1. **The model.** Does the derivation reflect what actually happens to a settler, and does the
   candidate know which parts are assumptions?
2. **The curve.** Is it right, is it explicable, and does the candidate know *why* it has the
   shape it has?
3. **Concurrency judgment.** What did you do about 50 live quotes and inventory for 10?
4. **Engineering.** Is the code something a colleague could pick up and change?

## Deliverable

A repo containing the code, the chart, and the two pages. A README with how to run it, your
seed, and — briefly — what you'd have done with more time.

**Stop at the ceiling.** "I ran out of room before doing X, and here's how I'd approach it" is a
better answer than a rushed X. We mean that; it is read, not penalized.

## The Review Call

We'll spend about 45 minutes together on your submission. It is a conversation about *your*
reasoning: expect to reproduce parts of the derivation live, to explain the shape of your curve,
and to answer what changes when the parameters move. Nothing to prepare — but we're interested
in how you think, so come ready to think out loud rather than to present.
