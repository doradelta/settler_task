//! Runs the engine against the spec's market for windows from 5 s to 5 min, prints the table, and writes
//! results/curve.csv, chart/markup_vs_window.svg and docs/data.js (the simulated dots on the interactive page).

use settler::{chart, pricing::Market, sim};

const SEED: u64 = 20261002;
const SECONDS: f64 = 120_000.0; // simulated seconds per point: 60 batches of 2,000 s
const WINDOWS: [f64; 11] = [5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 240.0, 300.0];

fn main() -> std::io::Result<()> {
    let spec = Market::default();
    let scenarios = [("spec", "Spec gas: 0.5 % to 2 % of the payment", spec), ("gas_div10", "Gas ÷ 10", spec.with_gas(0.1))];
    let mut csv = String::from("scenario,window_s,gaussian_bp,student_bp,engine_bp,ci_bp\n");
    let mut js = vec![];
    let mut panels = vec![];
    for (key, name, mk) in scenarios {
        println!("\n{name}  (gas floor {:.3} bp)", mk.gas_floor() * 1e4);
        println!("{:>7} {:>10} {:>10} {:>20}", "W (s)", "Gaussian", "Student-t", "engine, spec market");
        let points: Vec<_> = WINDOWS.iter().map(|&w| sim::breakeven(w, &mk, SECONDS, SEED)).collect();
        for p in &points {
            println!("{:>7} {:>10.3} {:>10.3} {:>12.3} ± {:.3}", p.window, p.gaussian_bp, p.student_bp, p.sim_bp, p.ci_bp);
            csv += &format!("{key},{},{:.6},{:.6},{:.6},{:.6}\n", p.window, p.gaussian_bp, p.student_bp, p.sim_bp, p.ci_bp);
        }
        let rows: Vec<String> = points.iter().map(|p| format!("{{\"window\":{},\"sim_bp\":{:.6},\"ci_bp\":{:.6}}}", p.window, p.sim_bp, p.ci_bp)).collect();
        js.push(format!("\"{key}\":{{\"rows\":[{}]}}", rows.join(",")));
        panels.push((name, mk.gas_floor() * 1e4, points));
    }
    std::fs::create_dir_all("results")?;
    std::fs::write("results/curve.csv", csv)?;
    std::fs::create_dir_all("chart")?;
    std::fs::write("chart/markup_vs_window.svg", chart::svg(&panels))?;
    std::fs::write("docs/data.js", format!("window.SIM = {{\"curve\":{{{}}}}};\n", js.join(",")))?;
    println!("\nwrote results/curve.csv, chart/markup_vs_window.svg and docs/data.js");
    Ok(())
}
