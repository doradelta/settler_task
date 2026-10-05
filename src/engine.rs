//! Part A: auction events in, quote-or-decline out. In memory, single process.
//!
//! Concurrency: a live quote reserves its payment of capital and an award keeps it locked until release,
//! so the engine only quotes what it can fund. With 50 live quotes and capital for 10, the 11th is declined.

use std::collections::HashMap;

use crate::pricing::{fair_markup, Market};

pub struct Auction {
    pub id: usize,
    pub opened_at: f64,
    pub fulfillment_deadline: f64,
    pub amount: f64,
}

#[derive(Clone, Debug)]
pub struct Quote {
    pub id: usize,
    pub quoted_at: f64,
    pub rate: f64,           // R0: the rate when we quoted
    pub markup: f64,
    pub price: f64,          // R0 · (1 + markup)
    pub amount: f64,
    pub award_deadline: f64, // min(now + W, fulfillment_deadline - latency)
    pub window: f64,         // award_deadline - quoted_at
}

#[derive(Debug, PartialEq)]
pub enum Decline {
    Infeasible, // the fulfillment deadline leaves less than the settlement latency
    NoCapital,  // every unit of capital is reserved or locked
}

pub struct Engine {
    market: Market,
    window: f64,               // W, how long we hold a price
    capital: f64,              // f64::INFINITY = unlimited
    fixed_markup: Option<f64>, // None = the fair markup for each quote's window
    in_use: f64,               // reserved by live quotes plus locked by awards
    live: HashMap<usize, Quote>,
    awarded: HashMap<usize, Quote>,
    markups: HashMap<i64, f64>, // fair markup per whole second of window
    next_id: usize,
}

impl Engine {
    pub fn new(market: Market, window: f64, capital: f64) -> Self {
        Engine { market, window, capital, fixed_markup: None, in_use: 0.0, live: HashMap::new(),
                 awarded: HashMap::new(), markups: HashMap::new(), next_id: 0 }
    }

    pub fn with_fixed_markup(self, markup: f64) -> Self {
        Engine { fixed_markup: Some(markup), ..self }
    }

    fn markup(&mut self, window: f64) -> f64 {
        if let Some(m) = self.fixed_markup {
            return m;
        }
        let key = window.round() as i64;
        *self.markups.entry(key).or_insert_with(|| fair_markup(key as f64, &self.market))
    }

    pub fn on_auction(&mut self, a: &Auction, now: f64, rate: f64) -> Result<Quote, Decline> {
        let latest_safe_bid = a.fulfillment_deadline - self.market.latency;
        if latest_safe_bid <= now {
            return Err(Decline::Infeasible);
        }
        if self.in_use + a.amount > self.capital {
            return Err(Decline::NoCapital);
        }
        let award_deadline = (now + self.window).min(latest_safe_bid);
        let markup = self.markup(award_deadline - now);
        self.in_use += a.amount;
        let q = Quote { id: self.next_id, quoted_at: now, rate, markup, price: rate * (1.0 + markup),
                        amount: a.amount, award_deadline, window: award_deadline - now };
        self.next_id += 1;
        self.live.insert(q.id, q.clone());
        Ok(q)
    }

    /// The originator accepted: the reserved capital stays locked until release.
    pub fn on_award(&mut self, id: usize, now: f64) -> bool {
        match self.live.get(&id) {
            Some(q) if now <= q.award_deadline => {
                let q = self.live.remove(&id).unwrap();
                self.awarded.insert(id, q);
                true
            }
            _ => false,
        }
    }

    /// The window closed without an award: the capital is free again.
    pub fn on_expiry(&mut self, id: usize) {
        if let Some(q) = self.live.remove(&id) {
            self.in_use -= q.amount;
        }
    }

    /// The destination chain confirmed and the escrow paid us: the capital is free again.
    pub fn on_release(&mut self, id: usize) {
        if let Some(q) = self.awarded.remove(&id) {
            self.in_use -= q.amount;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn auction(id: usize, now: f64, deadline: f64) -> Auction {
        Auction { id, opened_at: now, fulfillment_deadline: deadline, amount: 1000.0 }
    }

    #[test]
    fn declines_when_there_is_no_time_to_settle() {
        let mut engine = Engine::new(Market::default(), 60.0, f64::INFINITY);
        assert_eq!(engine.on_auction(&auction(0, 0.0, 20.0), 0.0, 1.0).unwrap_err(), Decline::Infeasible);
    }

    #[test]
    fn a_short_deadline_caps_the_window_and_the_price() {
        let mut engine = Engine::new(Market::default(), 300.0, f64::INFINITY);
        let capped = engine.on_auction(&auction(0, 0.0, 100.0), 0.0, 1.0).unwrap();
        let full = engine.on_auction(&auction(1, 0.0, 4000.0), 0.0, 1.0).unwrap();
        assert_eq!(capped.award_deadline, 76.0); // 100 - 24 s of latency
        assert!(capped.markup < full.markup);
    }

    #[test]
    fn fifty_live_quotes_and_capital_for_ten() {
        let mut engine = Engine::new(Market::default(), 60.0, 10_000.0);
        let results: Vec<_> = (0..50).map(|i| engine.on_auction(&auction(i, 0.0, 4000.0), 0.0, 1.0)).collect();
        assert_eq!(results.iter().filter(|r| r.is_ok()).count(), 10);
        assert!(results[10..].iter().all(|r| r.as_ref().unwrap_err() == &Decline::NoCapital));

        assert!(engine.on_award(0, 30.0)); // awarded: still locked
        assert!(engine.on_auction(&auction(50, 31.0, 4000.0), 31.0, 1.0).is_err());
        engine.on_release(0); // released: one payment of capital is free
        assert!(engine.on_auction(&auction(51, 200.0, 4000.0), 200.0, 1.0).is_ok());
        engine.on_expiry(1); // walked away: free again
        assert!(engine.on_auction(&auction(52, 201.0, 4000.0), 201.0, 1.0).is_ok());
    }

    #[test]
    fn no_award_after_the_deadline() {
        let mut engine = Engine::new(Market::default(), 60.0, f64::INFINITY);
        let q = engine.on_auction(&auction(0, 0.0, 4000.0), 0.0, 1.0).unwrap();
        assert!(!engine.on_award(q.id, 61.0));
    }
}
