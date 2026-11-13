"""figures/calibration.png from eval/figure_data_calibration.json (W2).

Three panels: the reliability diagram on the held-out test fold, the hit-rate shift between the
folds that explains the miscalibration, and the portfolio probability under both correlation
assumptions next to the number this work retracts.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def style():
    import matplotlib as mpl
    mpl.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 200, "font.size": 8.5, "axes.titlesize": 9,
        "axes.labelsize": 8.5, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
        "legend.fontsize": 7.5, "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#444444", "axes.linewidth": 0.8, "text.color": "#141821",
        "figure.facecolor": "white", "savefig.facecolor": "white"})


def bins(y, p, n_bins=10):
    order = np.argsort(p)
    y, p = np.asarray(y)[order], np.asarray(p)[order]
    out = []
    for b in np.array_split(np.arange(len(p)), n_bins):
        if len(b):
            out.append((p[b].mean(), y[b].mean(), len(b)))
    return out


def main() -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    style()
    d = json.load(open(os.path.join(HERE, "eval", "figure_data_calibration.json"),
                       encoding="utf-8"))
    cal = json.load(open(os.path.join(HERE, "eval", "calibration.json"), encoding="utf-8"))
    y = np.array(d["y_test"])
    sel = d["selected"]
    fig, axs = plt.subplots(1, 3, figsize=(11.6, 3.5))

    ax = axs[0]
    ax.plot([0, 1], [0, 1], ls="--", lw=0.9, color="#888", label="perfect calibration")
    for key, name, colour in ((f"p_selected", f"{sel} (fitted)", "#2b6cb0"),
                              ("p_legacy", "hand-written map (previous)", "#e05a5a")):
        bb = bins(y, np.array(d[key]))
        ax.plot([b[0] for b in bb], [b[1] for b in bb], "o-", ms=4, lw=1.2, color=colour,
                label=f"{name}, ECE {cal['test_metrics'][sel if key == 'p_selected' else 'uncalibrated_legacy_map']['ece_10bin']:.3f}")
    ax.axhline(y.mean(), color="#777", lw=0.7, ls=":")
    ax.text(0.98, y.mean() - 0.055, f"observed hit rate {y.mean():.2f}", fontsize=7,
            color="#555", ha="right")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("predicted P(hit)")
    ax.set_ylabel("observed fraction of hits")
    ax.legend(frameon=False, loc="lower right")
    ax.set_title("Neither map is calibrated (criterion: ECE $\\leq$ 0.10)")

    ax = axs[1]
    hr = cal["hit_rate"]
    names = ["calibration fold\n(n=%d)" % cal["split"]["calibration"],
             "test fold\n(n=%d)" % cal["split"]["test"]]
    vals = [hr["calibration"], hr["test"]]
    bars = ax.bar(names, vals, color=["#9aa3b2", "#2b6cb0"], width=0.55)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.3f}", ha="center", fontsize=8.5)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("fraction with measured pChEMBL $\\geq$ 7")
    ax.set_title("Why: the folds are not exchangeable")

    ax = axs[2]
    pf = cal["portfolio"]
    rows = [("retracted\n(hand-written map)", pf["legacy_uncalibrated_independent"], None,
             "#e05a5a"),
            ("calibrated,\nindependent", pf["p_at_least_one_independent"],
             pf["p_at_least_one_independent_ci95"], "#9aa3b2"),
            ("calibrated,\nfully correlated", pf["p_at_least_one_fully_correlated"],
             pf["p_at_least_one_fully_correlated_ci95"], "#2b6cb0")]
    ypos = np.arange(len(rows))[::-1]
    for yp, (lab, v, ci, colour) in zip(ypos, rows):
        ax.barh(yp, v, color=colour, height=0.5)
        if ci:
            ax.plot(ci, [yp, yp], color="#141821", lw=1.2)
            ax.plot([ci[0], ci[0]], [yp - 0.1, yp + 0.1], color="#141821", lw=1.2)
            ax.plot([ci[1], ci[1]], [yp - 0.1, yp + 0.1], color="#141821", lw=1.2)
        xt = (ci[1] if ci else v) + 0.03
        ax.text(xt, yp, f"{v:.3f}", va="center", ha="left", fontsize=8)
    ax.set_yticks(ypos)
    ax.set_yticklabels([r[0] for r in rows], fontsize=7.5)
    ax.set_xlim(0, 1.28)
    ax.set_xlabel("P($\\geq$1 hit) in a portfolio of %d" % pf["k"])
    ax.set_title("The correlation assumption decides it")

    fig.text(0.004, 0.025,
             "Held-out scaffold-split test fold, n=%d, target %s; hit = measured pChEMBL >= 7.0, "
             "declared before fitting (docs/preregistration.md W2). Calibrator: %s, fitted on the "
             "%d-molecule\ncalibration fold only, selected by 5-fold CV log-loss inside that "
             "fold. Intervals: 2000 bootstrap resamples of the calibration fold, refitting the "
             "calibrator each time."
             % (cal["split"]["test"], cal["target"], sel, cal["split"]["calibration"]),
             fontsize=6.3, color="#666", linespacing=1.5)
    fig.tight_layout(rect=(0, 0.085, 1, 1))
    out = os.path.join(HERE, "figures", "calibration.png")
    fig.savefig(out, dpi=200)
    print(f"{out}: selected={sel} ECE={cal['test_metrics'][sel]['ece_10bin']} "
          f"criterion_met={cal['criterion_met']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
