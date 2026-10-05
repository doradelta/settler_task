//! Part C: the engine against the spec's market.
//!
//! The market: R(t+1) = R(t)·exp(σZ) each second, Poisson auctions at 2 per second, 30 % informed originators,
//! fulfilment deadlines uniform up to 1 h ahead (the spec gives none). The engine quotes every auction at a fixed
//! markup and each quote's outcome follows from the rate path. Three markups around the model's m* give the
//! break-even markup, and 60 time batches its 95 % confidence interval.
//! Noise control: every run is averaged with its mirror path (-Z), and gas enters at its known mean.

use rand::{rngs::StdRng, Rng, SeedableRng};
use rand_distr::{Distribution, Exp, StandardNormal};

use crate::engine::{Auction, Engine};
use crate::pricing::{fair_markup, Market, SECONDS_PER_YEAR};

const BATCHES: usize = 60;

pub struct Tape {
    rate: Vec<f64>, // R(t), one value per second
    auctions: Vec<Auction>,
    informed: Vec<bool>, // the originator's hidden type
    u: Vec<f64>,         // an uninformed originator awards at quoted_at + u · window
}

pub fn spec_market(mk: &Market, seconds: f64, seed: u64, mirror: bool) -> Tape {
    let mut path = StdRng::seed_from_u64(seed); // the rate path
    let mut flow = StdRng::seed_from_u64(seed + 1); // the auctions, independent of the path
    let sign = if mirror { -1.0 } else { 1.0 };
    let mut log_r = 0.0;
    let mut rate = vec![1.0];
    for _ in 0..seconds as usize + 3700 { // the last fulfilment deadline is up to 1 h after the last auction
        let z: f64 = path.sample(StandardNormal);
        log_r += sign * mk.sigma * z;
        rate.push(f64::exp(log_r));
    }
    let gaps = Exp::new(2.0).unwrap();
    let (mut auctions, mut informed, mut u) = (vec![], vec![], vec![]);
    let mut t = gaps.sample(&mut flow);
    while t < seconds {
        auctions.push(Auction { id: auctions.len(), opened_at: t, fulfillment_deadline: t + 3600.0 * flow.gen::<f64>(),
                                amount: mk.notional });
        informed.push(flow.gen::<f64>() < mk.p_informed);
        u.push(flow.gen::<f64>());
        t += gaps.sample(&mut flow);
    }
    Tape { rate, auctions, informed, u }
}

/// Mean profit per quote in each time batch, at a fixed markup, over quotes that got the full window.
fn batch_means(markup: f64, window: f64, mk: &Market, tape: &Tape, seconds: f64) -> Vec<f64> {
    let r = |t: f64| tape.rate[t as usize];
    let mut engine = Engine::new(*mk, window, f64::INFINITY).with_fixed_markup(markup);
    let (mut sum, mut count) = ([0.0; BATCHES], [0usize; BATCHES]);
    for (i, a) in tape.auctions.iter().enumerate() {
        let Ok(q) = engine.on_auction(a, a.opened_at, r(a.opened_at)) else { continue };
        if q.award_deadline < a.opened_at + window {
            continue; // a short deadline cut the window: that is a different point on the curve
        }
        let t_award = if tape.informed[i] { q.award_deadline } else { q.quoted_at + tape.u[i] * q.window };
        let awarded = !tape.informed[i] || q.price < r(q.award_deadline);
        let held = if awarded { t_award + mk.latency + mk.lock - q.quoted_at } else { q.window };
        let mut pnl = -mk.cost_of_capital * q.amount * held / SECONDS_PER_YEAR;
        if awarded {
            let x = r(t_award + mk.latency) / q.rate; // how far the rate moved before we bought the units
            pnl += q.amount * (1.0 - x / (1.0 + q.markup)) - mk.gas_mean;
        }
        let b = (a.opened_at / seconds * BATCHES as f64) as usize;
        sum[b] += pnl;
        count[b] += 1;
    }
    (0..BATCHES).map(|b| sum[b] / count[b] as f64).collect()
}

/// The markup where mean profit crosses zero, from three (markup, profit) points.
/// Profit is linear in z = 1/(1+m) for the uninformed; a parabola absorbs the informed leg's curvature.
fn zero_crossing(ms: [f64; 3], y: [f64; 3]) -> f64 {
    let z = ms.map(|m| 1.0 / (1.0 + m));
    let (w0, w2) = (z[0] - z[1], z[2] - z[1]); // work in w = z - z[1], where the root is close to 0
    let d1 = (y[0] - y[1]) / w0;
    let a = ((y[2] - y[0]) / (w2 - w0) - d1) / w2;
    let (b, c) = (d1 - a * w0, y[1]);
    let disc = b * b - 4.0 * a * c;
    let w = if a == 0.0 || disc < 0.0 { -c / b } else { -2.0 * c / (b + b.signum() * disc.sqrt()) };
    1.0 / (z[1] + w) - 1.0
}

pub struct Point {
    pub window: f64,
    pub gaussian_bp: f64, // the model with the spec's Gaussian returns
    pub student_bp: f64,  // the model with Student-t returns
    pub sim_bp: f64,      // the engine's break-even on the spec market
    pub ci_bp: f64,       // 95 % half-width
}

pub fn breakeven(window: f64, mk: &Market, seconds: f64, seed: u64) -> Point {
    let m0 = fair_markup(window, &mk.gaussian());
    let ms = [m0 - 1e-4, m0, m0 + 1e-4];
    let tapes = [spec_market(mk, seconds, seed, false), spec_market(mk, seconds, seed, true)];
    let means: Vec<Vec<f64>> = ms.iter().map(|&m| {
        let (a, b) = (batch_means(m, window, mk, &tapes[0], seconds), batch_means(m, window, mk, &tapes[1], seconds));
        a.iter().zip(&b).map(|(x, y)| 0.5 * (x + y)).collect()
    }).collect();
    let avg = |v: &[f64]| v.iter().sum::<f64>() / v.len() as f64;
    let roots: Vec<f64> = (0..BATCHES).map(|b| zero_crossing(ms, [means[0][b], means[1][b], means[2][b]])).collect();
    let mean = avg(&roots);
    let sd = (roots.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / (BATCHES - 1) as f64).sqrt();
    Point {
        window,
        gaussian_bp: m0 * 1e4,
        student_bp: fair_markup(window, mk) * 1e4,
        sim_bp: zero_crossing(ms, [avg(&means[0]), avg(&means[1]), avg(&means[2])]) * 1e4,
        ci_bp: 2.0 * sd / (BATCHES as f64).sqrt() * 1e4, // t quantile for 59 degrees of freedom ≈ 2.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_engine_breaks_even_where_the_gaussian_model_says() {
        let p = breakeven(60.0, &Market::default().with_gas(0.1), 40_000.0, 7); // cheap gas: the option leg is exercised
        assert!((p.sim_bp - p.gaussian_bp).abs() < 3.0 * p.ci_bp + 1e-3);
    }

    #[test]
    fn zero_crossing_is_exact_for_a_parabola_in_z() {
        let root = 0.0127;
        let f = |m: f64| { let z = 1.0 / (1.0 + m); let zr = 1.0 / (1.0 + root); (z - zr) * (3.0 + 50.0 * (z - zr)) };
        let ms = [0.0125, 0.0126, 0.0127 + 3e-5];
        assert!((zero_crossing(ms, ms.map(f)) - root).abs() < 1e-12);
    }
}
