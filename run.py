"""Reproduces every number in the README: results/results.json, docs/data.js and chart/markup_vs_window.png."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from settler import Market, Sizes, bid_price, breakeven, capacity_run, gas_floor  # noqa: E402

SEED = 20261002
WINDOWS = [5, 10, 20, 30, 45, 60, 90, 120, 180, 240, 300]
CAPITALS = [10_000, 20_000, 50_000, 100_000, 200_000, 500_000]
MARKUP, WINDOW, ARRIVALS, SIZES = 0.015, 60.0, 2.0, Sizes(1000.0, 0.8)   # problem 2: a 150 bp quote, 1-minute window
ROOT = Path(__file__).resolve().parent


def main() -> None:
    spec = Market()
    out = {"seed": SEED, "curve": {}, "allocation": {"markup_bp": MARKUP * 1e4, "window": WINDOW, "arrival_rate": ARRIVALS,
                                                      "size_median": SIZES.median, "size_log_sd": SIZES.log_sd, "rows": []}}
    for name, mk in (("spec", spec), ("gas_div10", spec.with_gas(0.1))):
        rows = [breakeven(w, mk, seed=SEED) for w in WINDOWS]
        out["curve"][name] = {"gas_mean": mk.gas_mean, "floor_bp": gas_floor(mk) * 1e4, "rows": rows}
        for r in rows:
            print(f"{name:9s} W={r['window']:4.0f}  gaussian {r['gaussian_bp']:8.3f}  student-t {r['student_bp']:8.3f}  "
                  f"simulated {r['sim_bp']:8.3f} ± {r['ci_bp']:.3f} bp   informed exercises {r['informed_fills']}")
    for capital in CAPITALS:
        bp = bid_price(MARKUP, WINDOW, spec, capital, ARRIVALS, SIZES)
        fcfs = capacity_run(WINDOW, spec, capital, MARKUP, seed=SEED, sizes=SIZES, arrival_rate=ARRIVALS)
        bid = capacity_run(WINDOW, spec, capital, MARKUP, seed=SEED, sizes=SIZES, min_size=bp.min_size, arrival_rate=ARRIVALS)
        row = {"capital": capital, "min_size": bp.min_size, "bid_price_bp_per_hour": bp.bid_price * 3600 * 1e4,
               "accept_share": bp.accept_share, "utilisation": bp.utilisation,
               "closed_bid_profit_per_hour": bp.profit_per_s * 3600,
               "sim_bid_profit_per_hour": bid["profit_per_s"] * 3600, "sim_fcfs_profit_per_hour": fcfs["profit_per_s"] * 3600,
               "sim_bid_utilisation": bid["utilisation"], "sim_fcfs_utilisation": fcfs["utilisation"]}
        out["allocation"]["rows"].append(row)
        print(f"capital {capital:7d}  quote sizes ≥ {bp.min_size:6.0f}  bid price {row['bid_price_bp_per_hour']:6.1f} bp/h  "
              f"profit/h: bid price {row['closed_bid_profit_per_hour']:7.1f} fluid, {row['sim_bid_profit_per_hour']:7.1f} engine;  "
              f"quote everything {row['sim_fcfs_profit_per_hour']:7.1f} engine")

    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "results.json").write_text(json.dumps(out, indent=1))
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "data.js").write_text("window.SIM = " + json.dumps(out) + ";\n")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4), dpi=160)
    for ax, (name, title) in zip(axes, (("spec", "Spec gas: U(0.5%, 2%) of the payment"), ("gas_div10", "Gas ÷ 10"))):
        c = out["curve"][name]
        w = [r["window"] for r in c["rows"]]
        ax.axhline(c["floor_bp"], color="#9aa3ad", lw=1, ls=":", label="gas floor")
        ax.plot(w, [r["gaussian_bp"] for r in c["rows"]], color="#d2602c", lw=2, label="model, Gaussian (ν = ∞)")
        ax.plot(w, [r["student_bp"] for r in c["rows"]], color="#1f4f8f", lw=2, label="model, Student-t (ν = 4)")
        ax.errorbar(w, [r["sim_bp"] for r in c["rows"]], yerr=[r["ci_bp"] for r in c["rows"]], fmt="o", ms=4,
                    color="#142033", capsize=3, lw=1, label="quote rule on the spec market, 95% CI")
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("award window W (s)")
        ax.set_ylabel("markup (bp)")
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8, loc="upper left")
    fig.suptitle("Fair markup vs award window, 5 s to 5 min (seed 20261002, 120,000 s per point)", fontsize=12)
    fig.tight_layout()
    (ROOT / "chart").mkdir(exist_ok=True)
    fig.savefig(ROOT / "chart" / "markup_vs_window.png")
    print("wrote results/results.json, docs/data.js, chart/markup_vs_window.png")


if __name__ == "__main__":
    main()
