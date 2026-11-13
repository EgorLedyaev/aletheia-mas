"""Regenerate figures/eval_dashboard.png from eval/harness_report.json + eval/funnel_table.json.

Panel (d) now shows BOTH funnel runs side by side: the two runs were previously conflated, and
plotting one of them alone is what let a stale number survive in the documents.
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
        "figure.dpi": 110, "savefig.dpi": 200, "font.size": 8, "axes.titlesize": 9,
        "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
        "axes.titlepad": 7, "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#444444", "axes.linewidth": 0.8, "xtick.color": "#444444",
        "ytick.color": "#444444", "text.color": "#141821", "axes.labelcolor": "#141821",
        "figure.facecolor": "white", "savefig.facecolor": "white"})


def main() -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    style()
    rep = json.load(open(os.path.join(HERE, "eval", "harness_report.json"), encoding="utf-8"))
    ft = json.load(open(os.path.join(HERE, "eval", "funnel_table.json"), encoding="utf-8"))
    F = {f["scenario"]: f["counts"] for f in ft["funnels"]}

    fig, axs = plt.subplots(1, 4, figsize=(13.2, 3.4))

    # (a) traceability
    mas = rep["mas_on_baseline_subset"]
    b1, b2 = rep["baselines"]["B1_plain_llm"], rep["baselines"]["B2_single_agent"]
    ax = axs[0]
    names = ["plain LLM\n(no tools)", "single agent\nwith tools", "Aletheia\n(this system)"]
    trace = [0.0, 0.0, mas["mean_ledger_coverage"] * 100]
    bars = ax.bar(names, trace, color=["#c3c8d2", "#9aa3b2", "#2b6cb0"], width=0.6)
    for b, v in zip(bars, trace):
        ax.text(b.get_x() + b.get_width() / 2, v + 3, f"{v:.0f}%", ha="center", fontsize=8.5)
    ax.set_ylim(0, 112)
    ax.set_ylabel("numeric claims resolvable to a tool run (%)")
    ax.set_title("Only the ledger makes numbers checkable")

    # (b) orchestration
    ax = axs[1]
    pats = ["supervisor", "blackboard"]
    pr = [rep["orchestration"][p]["summary"]["pass_rate"] * 100 for p in pats]
    md = [rep["orchestration"][p]["summary"]["median_duration_s"] for p in pats]
    xx, w = np.arange(2), 0.36
    ax.bar(xx - w / 2, pr, width=w, color="#2b6cb0")
    ax2 = ax.twinx()
    ax2.bar(xx + w / 2, md, width=w, color="#e0803a")
    ax.set_xticks(xx)
    ax.set_xticklabels(pats)
    ax.set_ylim(0, 118)
    ax.set_ylabel("scenarios passed (%)", color="#2b6cb0")
    ax.tick_params(axis="y", colors="#2b6cb0")
    ax2.set_ylabel("median latency (s), warm cache", color="#e0803a")
    ax2.tick_params(axis="y", colors="#e0803a")
    ax2.set_ylim(0, max(md) * 1.7)
    for i, v in enumerate(pr):
        ax.text(i - w / 2, v + 3, f"{v:.0f}", ha="center", fontsize=7.5, color="#2b6cb0")
    for i, v in enumerate(md):
        ax2.text(i + w / 2, v + 0.008, f"{v:.2f}", ha="center", fontsize=7.5, color="#e0803a")
    ax.set_title("Both patterns pass; latency differs little")

    # (c) ablations
    ax = axs[2]
    abl = rep["ablations"]
    rows = [("full system", 11, 11),
            ("no critic", abl["no_critic"]["summary"]["n_passed"], abl["no_critic"]["summary"]["n"]),
            ("single generator", abl["single_generator"]["summary"]["n_passed"],
             abl["single_generator"]["summary"]["n"]),
            ("no guardrail", abl["no_guardrail"]["summary"]["n_passed"],
             abl["no_guardrail"]["summary"]["n"])]
    lbl = [r[0] for r in rows]
    frac = [(r[1] / r[2]) * 100 for r in rows]
    colr = ["#2b6cb0", "#9aa3b2", "#e0803a", "#e05a5a"]
    bb = ax.barh(lbl[::-1], frac[::-1], color=colr[::-1], height=0.55)
    for b, r0 in zip(bb, rows[::-1]):
        inside = b.get_width() > 40
        ax.text(b.get_width() - 3 if inside else b.get_width() + 2,
                b.get_y() + b.get_height() / 2, f"{r0[1]}/{r0[2]}", va="center",
                ha="right" if inside else "left", fontsize=7.5,
                color="#fff" if inside else "#333")
    ax.set_xlim(0, 112)
    ax.set_xlabel("invariant checks passed (%)")
    ax.set_title("Removing a component breaks the check it owns")

    # (d) funnel, both runs
    ax = axs[3]
    stages = [("after_hazard_gate", "entering\ngate 1"), ("gate1_passed", "survive\ngate 1"),
              ("oracle_scored", "scored by\nthe model"), ("portfolio", "in the\nportfolio")]
    x = np.arange(len(stages))
    w = 0.38
    for i, (scen, colour) in enumerate([("S07", "#9aa3b2"), ("S08", "#2b6cb0")]):
        vals = [F[scen][k] or 0 for k, _ in stages]
        ax.bar(x + (i - 0.5) * w, vals, width=w, color=colour, label=scen)
        for xi, v in zip(x + (i - 0.5) * w, vals):
            ax.text(xi, v + 3, str(v), ha="center", fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels([lab for _, lab in stages], fontsize=6.6)
    ax.set_ylabel("molecules")
    ax.set_ylim(0, max(F["S08"]["after_hazard_gate"], F["S07"]["after_hazard_gate"]) * 1.25)
    ax.legend(frameon=False, fontsize=7, loc="upper right")
    ax.set_title("Same gate, two seeds")

    fig.text(0.004, 0.030,
             "Panels a-c: 11 fast scenarios, warm cache, supervisor pattern unless stated; "
             "baselines measured on S01/S04/S05 (mean tool calls per query: plain LLM 0, single "
             "agent 7, Aletheia 58). Ablation rows are scored only on the scenarios whose "
             "invariants the removed component owns.", fontsize=6.2, color="#666")
    fig.text(0.004, 0.008,
             "Panel d: canonical counts from docs/funnel_table.md (scripts/funnel_report.py). "
             "S07 is seeded with the erlotinib SMILES in its query, S08 with the most potent "
             "retrieved active; gate thresholds are identical.", fontsize=6.2, color="#666")
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    out = os.path.join(HERE, "figures", "eval_dashboard.png")
    fig.savefig(out, dpi=200)
    print(f"{out}: funnel panel S07={[F['S07'][k] for k, _ in stages]} "
          f"S08={[F['S08'][k] for k, _ in stages]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
