"""figures/baseline_study.png from eval/baseline_study.json (W4).

Three panels: correctness (where the baselines win), numeric traceability (where they cannot
follow), and the price in latency. The discovery run that found five defects in our own system is
plotted beside the post-fix run, because hiding it would make the study look like a victory lap.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABEL = {"B1_plain_llm": "plain LLM\n(no tools)", "B2_single_agent": "single agent\n+ tools",
         "B3_single_agent_ledger": "single agent\n+ our ledger", "MAS_aletheia": "Aletheia"}
ORDER = ["B1_plain_llm", "B2_single_agent", "B3_single_agent_ledger", "MAS_aletheia"]
COL = {"B1_plain_llm": "#c3c8d2", "B2_single_agent": "#9aa3b2",
       "B3_single_agent_ledger": "#6b7684", "MAS_aletheia": "#2b6cb0"}


def style():
    import matplotlib as mpl
    mpl.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 200, "font.size": 8.5, "axes.titlesize": 9,
        "axes.labelsize": 8.5, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
        "legend.fontsize": 7.5, "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#444444", "axes.linewidth": 0.8, "text.color": "#141821",
        "figure.facecolor": "white", "savefig.facecolor": "white"})


def main() -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    style()
    with open(os.path.join(HERE, "eval", "baseline_study.json"), encoding="utf-8") as fh:
        post = json.load(fh)
    disc_path = os.path.join(HERE, "eval", "baseline_study_discovery.json")
    disc = None
    if os.path.exists(disc_path):
        with open(disc_path, encoding="utf-8") as fh:
            disc = json.load(fh)
    S = post["summary"]
    fig, axs = plt.subplots(1, 3, figsize=(11.8, 3.6))

    ax = axs[0]
    x = np.arange(len(ORDER))
    w = 0.38 if disc else 0.6
    if disc:
        dv = [disc["summary"][s]["correctness"] for s in ORDER]
        ax.bar(x - w / 2, dv, width=w, color="#e0a0a0",
               label="first run (found 5 defects in us)")
        for xi, v in zip(x - w / 2, dv):
            ax.text(xi, v + 0.015, f"{v:.2f}", ha="center", fontsize=7)
    pv = [S[s]["correctness"] for s in ORDER]
    ax.bar(x + (w / 2 if disc else 0), pv, width=w, color=[COL[s] for s in ORDER],
           label="after the fixes")
    for xi, v in zip(x + (w / 2 if disc else 0), pv):
        ax.text(xi, v + 0.015, f"{v:.2f}", ha="center", fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels([LABEL[s] for s in ORDER], fontsize=7)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("fraction of 24 queries answered correctly")
    ax.legend(frameon=False, fontsize=6.8, loc="lower left")
    ax.set_title("A single agent with our ledger is still the most accurate")

    ax = axs[1]
    cov = [S[s]["mean_numeric_coverage"] for s in ORDER]
    vals = [0.0 if c is None else c for c in cov]
    bars = ax.bar(x, vals, color=[COL[s] for s in ORDER], width=0.6)
    for b, c in zip(bars, cov):
        ax.text(b.get_x() + b.get_width() / 2, (c or 0) + 0.02,
                "none by\nconstruction" if c is None else f"{c:.2f}", ha="center", fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels([LABEL[s] for s in ORDER], fontsize=7)
    ax.set_ylim(0, 1.2)
    ax.set_ylabel("published numbers resolvable to a tool call")
    ax.set_title("A ledger nobody must cite is not provenance")

    ax = axs[2]
    lat = [S[s]["median_latency_s"] or 0 for s in ORDER]
    bars = ax.barh([LABEL[s].replace("\n", " ") for s in ORDER][::-1], lat[::-1],
                   color=[COL[s] for s in ORDER][::-1], height=0.55)
    for b, v in zip(bars, lat[::-1]):
        ax.text(v + max(lat) * 0.02, b.get_y() + b.get_height() / 2, f"{v:.2f} s",
                va="center", fontsize=7.5)
    ax.set_xlim(0, max(lat) * 1.25 if max(lat) else 1)
    ax.set_xlabel("median latency per query (s, warm caches)")
    ax.set_title("And it costs time")

    nz = {s: S[s]["identifiers_nonexistent"] for s in ORDER}
    fig.text(0.004, 0.025,
             f"24 queries across {len(post['tracks'])} tracks; ground truth recomputed at run time "
             f"by RDKit, UniProt, RCSB and PubChem. Identifiers that do not exist, after separating "
             f"a database outage from a fabrication: "
             + ", ".join(f"{LABEL[s].splitlines()[0]} {nz[s]}" for s in ORDER)
             + ". Data: eval/baseline_study.json, eval/baseline_study_discovery.json.",
             fontsize=6.3, color="#666")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(os.path.join(HERE, "figures", "baseline_study.png"), dpi=200)
    print("correctness " + " ".join(f"{s}={S[s]['correctness']}" for s in ORDER))
    return 0


if __name__ == "__main__":
    sys.exit(main())
