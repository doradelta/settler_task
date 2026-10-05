//! The one required chart, as a plain SVG: model lines and the engine's simulated break-even, two panels.

use crate::sim::Point;

const BLUE: &str = "#1f4f8f";
const ORANGE: &str = "#d2602c";
const INK: &str = "#142033";
const GREY: &str = "#9aa3ad";

/// Round tick positions covering [lo, hi].
fn ticks(lo: f64, hi: f64) -> Vec<f64> {
    let raw = (hi - lo) / 6.0;
    let p = 10f64.powf(raw.log10().floor());
    let step = p * [1.0, 2.0, 2.5, 5.0, 10.0].into_iter().find(|&f| f * p >= raw).unwrap();
    let mut v = (lo / step).ceil() * step;
    let mut out = vec![];
    while v <= hi + 1e-12 {
        out.push(v);
        v += step;
    }
    out
}

pub fn svg(panels: &[(&str, f64, Vec<Point>)]) -> String {
    let mut s = String::from(r##"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 470" font-family="Helvetica, Arial, sans-serif" font-size="12" fill="#3c4859">
<rect width="1100" height="470" fill="white"/>
<text x="550" y="26" text-anchor="middle" font-size="15" fill="#142033">Fair markup vs award window, 5 s to 5 min (seed 20261002, 120,000 s per point)</text>
"##);
    for (i, (title, floor, pts)) in panels.iter().enumerate() {
        let (x0, y0, pw, ph) = (80.0 + 545.0 * i as f64, 60.0, 440.0, 320.0);
        let values = pts.iter().flat_map(|p| [p.gaussian_bp, p.student_bp, p.sim_bp + p.ci_bp, p.sim_bp - p.ci_bp]);
        let (lo, hi) = values.chain([*floor]).fold((f64::MAX, f64::MIN), |(a, b), v| (a.min(v), b.max(v)));
        let (lo, hi) = (lo - 0.08 * (hi - lo), hi + 0.08 * (hi - lo));
        let x = |w: f64| x0 + w / 300.0 * pw;
        let y = |v: f64| y0 + (1.0 - (v - lo) / (hi - lo)) * ph;
        let decimals = if hi - lo < 0.5 { 2 } else { 1 };

        s += &format!("<text x=\"{}\" y=\"50\" text-anchor=\"middle\" font-size=\"13\" fill=\"{INK}\">{title}</text>\n", x0 + pw / 2.0);
        for v in ticks(lo, hi) {
            s += &format!("<line x1=\"{x0}\" x2=\"{}\" y1=\"{:.1}\" y2=\"{:.1}\" stroke=\"#e6eaef\"/><text x=\"{}\" y=\"{:.1}\" text-anchor=\"end\">{v:.decimals$}</text>\n",
                          x0 + pw, y(v), y(v), x0 - 8.0, y(v) + 4.0);
        }
        for w in [0.0, 60.0, 120.0, 180.0, 240.0, 300.0] {
            s += &format!("<text x=\"{:.1}\" y=\"{}\" text-anchor=\"middle\">{w}</text>\n", x(w), y0 + ph + 18.0);
        }
        s += &format!("<rect x=\"{x0}\" y=\"{y0}\" width=\"{pw}\" height=\"{ph}\" fill=\"none\" stroke=\"#c3c2b7\"/>\n");
        s += &format!("<text x=\"{}\" y=\"{}\" text-anchor=\"middle\">award window W (s)</text>\n", x0 + pw / 2.0, y0 + ph + 38.0);
        s += &format!("<text transform=\"translate({},{}) rotate(-90)\" text-anchor=\"middle\">markup (bp)</text>\n", x0 - 58.0, y0 + ph / 2.0);
        s += &format!("<line x1=\"{x0}\" x2=\"{}\" y1=\"{:.1}\" y2=\"{:.1}\" stroke=\"{GREY}\" stroke-dasharray=\"3 4\"/>\n", x0 + pw, y(*floor), y(*floor));

        let line = |f: &dyn Fn(&Point) -> f64| pts.iter().map(|p| format!("{:.1},{:.1}", x(p.window), y(f(p)))).collect::<Vec<_>>().join(" ");
        s += &format!("<polyline points=\"{}\" fill=\"none\" stroke=\"{ORANGE}\" stroke-width=\"2\"/>\n", line(&|p| p.gaussian_bp));
        s += &format!("<polyline points=\"{}\" fill=\"none\" stroke=\"{BLUE}\" stroke-width=\"2\"/>\n", line(&|p| p.student_bp));
        for p in pts {
            s += &format!("<line x1=\"{0:.1}\" x2=\"{0:.1}\" y1=\"{1:.1}\" y2=\"{2:.1}\" stroke=\"{INK}\"/><circle cx=\"{0:.1}\" cy=\"{3:.1}\" r=\"3.5\" fill=\"{INK}\"/>\n",
                          x(p.window), y(p.sim_bp - p.ci_bp), y(p.sim_bp + p.ci_bp), y(p.sim_bp));
        }
    }
    let legend = [(GREY, "gas floor", true), (ORANGE, "model, Gaussian (ν = ∞)", false), (BLUE, "model, Student-t (ν = 4)", false),
                  (INK, "engine on the spec market, 95 % CI", false)];
    for (j, (color, label, dashed)) in legend.iter().enumerate() {
        let lx = 150.0 + 220.0 * j as f64;
        let dash = if *dashed { " stroke-dasharray=\"3 4\"" } else { "" };
        s += &format!("<line x1=\"{lx}\" x2=\"{}\" y1=\"448\" y2=\"448\" stroke=\"{color}\" stroke-width=\"2\"{dash}/><text x=\"{}\" y=\"452\">{label}</text>\n", lx + 22.0, lx + 28.0);
    }
    s + "</svg>\n"
}
