//! Part B: the fair markup for a firm quote held open W seconds.
//!
//! A firm quote is a call the originator holds for free: strike = our price, expiry = award_deadline.
//! The fair markup m* solves  (1-p)·E[profit | uninformed] + p·E[profit | informed] - carry = 0.
//! m is both our revenue and the strike, so it is a fixed point, found by bisection.
//! The option is priced with Bachelier (additive moves, the short-horizon option model) and Student-t
//! returns scaled to variance σ²W; ν = ∞ is the Gaussian the spec simulates.

use statrs::distribution::{Continuous, ContinuousCDF, Normal, StudentsT};

pub const SECONDS_PER_YEAR: f64 = 31_557_600.0;

#[derive(Clone, Copy, Debug)]
pub struct Market {
    pub notional: f64,        // N, source units per payment
    pub sigma: f64,           // rate volatility per √second (2 bp)
    pub nu: f64,              // Student-t degrees of freedom; f64::INFINITY = Gaussian
    pub p_informed: f64,      // share of originators who award only if the rate beat our price
    pub gas_mean: f64,        // expected gas per fill (spec: uniform 5 to 20)
    pub latency: f64,         // L: award to fulfilment, seconds (2 Ethereum blocks)
    pub lock: f64,            // fulfilment to release, seconds (12 blocks × 12 s)
    pub cost_of_capital: f64, // per year, on the payment a quote ties up
}

impl Default for Market {
    fn default() -> Self {
        Market { notional: 1000.0, sigma: 2e-4, nu: 4.0, p_informed: 0.3, gas_mean: 12.5,
                 latency: 24.0, lock: 144.0, cost_of_capital: 0.10 }
    }
}

impl Market {
    pub fn gaussian(self) -> Self {
        Market { nu: f64::INFINITY, ..self }
    }

    pub fn with_gas(self, factor: f64) -> Self {
        Market { gas_mean: self.gas_mean * factor, ..self }
    }

    /// The markup whose revenue N·m/(1+m) pays the expected gas: 126.6 bp at the spec.
    pub fn gas_floor(&self) -> f64 {
        self.gas_mean / (self.notional - self.gas_mean)
    }
}

/// The option: E[(r - k)+] and P(r > k), for a move r with standard deviation s and a Student-t(ν) shape.
pub fn tail_call(k: f64, s: f64, nu: f64) -> (f64, f64) {
    if s <= 0.0 {
        return ((-k).max(0.0), if k < 0.0 { 1.0 } else { 0.0 });
    }
    if nu.is_infinite() {
        let z = Normal::new(0.0, 1.0).unwrap();
        let a = k / s;
        return (s * (z.pdf(a) - a * z.sf(a)), z.sf(a));
    }
    let t = StudentsT::new(0.0, 1.0, nu).unwrap();
    let c = s * ((nu - 2.0) / nu).sqrt(); // rescale so the variance is s²
    let a = k / c;
    (c * ((nu + a * a) / (nu - 1.0) * t.pdf(a) - a * t.sf(a)), t.sf(a))
}

/// Expected profit per quote at markup m for a window W, and q = P(an informed originator awards).
pub fn expected_pnl(m: f64, window: f64, mk: &Market) -> (f64, f64) {
    let (n, p, k) = (mk.notional, mk.p_informed, 1.0 + m);
    let drift = 1.0 + mk.sigma.powi(2) * (window / 4.0 + mk.latency / 2.0); // the spec's rate drifts up slightly
    let uninformed = n * (1.0 - drift / k) - mk.gas_mean; // awards at a random time, whatever the price
    let (call, q) = tail_call(m, mk.sigma * window.sqrt(), mk.nu);
    let informed = -(n / k * call + mk.gas_mean * q); // awards only when the rate beat us: a short call
    let settle = mk.latency + mk.lock;
    let held = (1.0 - p) * (window / 2.0 + settle) + p * (window + q * settle); // capital reserved, then locked
    let carry = mk.cost_of_capital * n * held / SECONDS_PER_YEAR;
    ((1.0 - p) * uninformed + p * informed - carry, q)
}

/// Break-even markup m*(W). Profit rises with m (more revenue, a dearer strike), so there is one root.
pub fn fair_markup(window: f64, mk: &Market) -> f64 {
    let (mut lo, mut hi) = (0.0, 0.5);
    for _ in 0..100 {
        let mid = 0.5 * (lo + hi);
        if expected_pnl(mid, window, mk).0 > 0.0 { hi = mid } else { lo = mid }
    }
    0.5 * (lo + hi)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn integrate(f: impl Fn(f64) -> f64, a: f64, b: f64) -> f64 {
        let n = 200_000; // Simpson's rule
        let h = (b - a) / n as f64;
        (0..=n).map(|i| f(a + i as f64 * h) * if i == 0 || i == n { 1.0 } else if i % 2 == 1 { 4.0 } else { 2.0 }).sum::<f64>() * h / 3.0
    }

    #[test]
    fn option_formula_matches_numerical_integration() {
        for (nu, k) in [(3.0, 0.5), (4.0, 2.0), (4.0, 5.0), (f64::INFINITY, 1.0)] {
            let pdf = |r: f64| if nu.is_infinite() {
                Normal::new(0.0, 1.0).unwrap().pdf(r)
            } else {
                let c = ((nu - 2.0) / nu).sqrt();
                StudentsT::new(0.0, 1.0, nu).unwrap().pdf(r / c) / c
            };
            let (call, q) = tail_call(k, 1.0, nu);
            assert!((call - integrate(|r| (r - k) * pdf(r), k, k + 400.0)).abs() < 1e-4 * call);
            assert!((q - integrate(pdf, k, k + 400.0)).abs() < 1e-4 * q);
        }
    }

    #[test]
    fn no_rate_risk_means_the_gas_floor() {
        let mk = Market { sigma: 0.0, cost_of_capital: 0.0, ..Market::default() };
        assert!((fair_markup(300.0, &mk) - mk.gas_floor()).abs() < 1e-12);
    }

    #[test]
    fn a_longer_window_costs_more() {
        let mk = Market::default();
        let m: Vec<f64> = [5.0, 60.0, 300.0, 1200.0].iter().map(|&w| fair_markup(w, &mk)).collect();
        assert!(m.windows(2).all(|p| p[1] > p[0]));
    }

    #[test]
    fn student_t_tends_to_the_gaussian() {
        let gauss = fair_markup(300.0, &Market::default().gaussian());
        let big_nu = fair_markup(300.0, &Market { nu: 1e7, ..Market::default() });
        assert!((gauss - big_nu).abs() < 1e-8);
    }

    #[test]
    fn spec_numbers() {
        let bp = |w: f64, mk: Market| fair_markup(w, &mk) * 1e4;
        assert!((bp(5.0, Market::default().gaussian()) - 126.593).abs() < 5e-4);
        assert!((bp(300.0, Market::default().gaussian()) - 126.640).abs() < 5e-4);
        assert!((bp(300.0, Market::default()) - 126.880).abs() < 5e-4);
    }
}
