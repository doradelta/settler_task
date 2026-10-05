"""Reproduces every number in the README: results/results.json, docs/data.js and chart/markup_vs_window.png."""
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from settler import Market, breakeven, capacity_run, gas_floor  # noqa: E402

SEED = 20261002
WINDOWS = [5, 10, 20, 30, 45, 60, 90, 120, 180, 240, 300]
ROOT = Path(__file__).resolve().parent


def main() -> None:
    spec = Market()
    out = {"seed": SEED, "curve": {}, "capacity": [], "overbooking": []}
    for name, mk in (("spec", spec), ("gas_div10", spec.with_gas(0.1))):
        rows = [breakeven(w, mk, seed=SEED) for w in WINDOWS]
        out["curve"][name] = {"gas_mean": mk.gas_mean, "floor_bp": gas_floor(mk) * 1e4, "rows": rows}
        for r in rows:
            print(f"{name:9s} W={r['window']:4.0f}  gaussian {r['gaussian_bp']:8.3f}  student-t {r['student_bp']:8.3f}  "
                  f"simulated {r['sim_bp']:8.3f} ± {r['ci_bp']:.3f} bp   informed exercises {r['informed_fills']}")
    for w in (5, 30, 60, 120, 300):
        out["capacity"].append(capacity_run(w, spec, 10, seed=SEED))
        print("capacity 10", {k: round(v, 4) for k, v in out["capacity"][-1].items()})
    for penalty in (math.inf, 10.0, 5.0, 3.0):
        r = capacity_run(300, spec, 10, seed=SEED, margin=1.0, penalty=penalty)
        out["overbooking"].append({"penalty": penalty if math.isfinite(penalty) else None, **r})
        print("overbooking F =", penalty, {k: round(v, 4) for k, v in r.items()})

    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "results.json").write_text(json.dumps(out, indent=1))
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
