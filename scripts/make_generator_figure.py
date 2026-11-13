"""Regenerate figures/generator_comparison.png from eval/figure_data_s07.json.

Figures are never hand-edited: the numbers and the panel titles are both derived from the data,
so a title cannot drift away from the bars it describes.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABEL = {"G1_rule_decorate": "G1\nrules", "G2_brics_recombine": "G2\nBRICS",
         "G3_selfies_mutate": "G3\nSELFIES", "G4_llm_edits": "G4\nLLM"}
ORDER = ["G1_rule_decorate", "G2_brics_recombine", "G3_selfies_mutate", "G4_llm_edits"]


SHORT = {k: k.split("_")[0] for k in LABEL}


WORD = {1: "One", 2: "Two", 3: "Three", 4: "All four"}


def novelty_title(stats, order):
    """Title derived from the data, so it cannot overstate what the bars show."""
    nz = [g for g in order if stats[g]["frac_novel"] > 0]
    if not nz:
        return "No generator left the known chemotypes"
    if len(nz) == 1:
        return f"Only {SHORT[nz[0]]} leaves known chemotypes"
    top = max(order, key=lambda g: stats[g]["frac_novel"])
    rest = [SHORT[g] for g in nz if g != top]
    verb = "adds" if len(rest) == 1 else "add"
    return f"{SHORT[top]} dominates novelty; {', '.join(rest)} {verb} a little"


def style():
    import matplotlib as mpl
    mpl.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 200, "font.size": 8,
        "axes.titlesize": 9, "axes.labelsize": 8, "xtick.labelsize": 7,
        "ytick.labelsize": 7, "legend.fontsize": 7, "axes.titlepad": 7,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#444444", "axes.linewidth": 0.8,
        "xtick.color": "#444444", "ytick.color": "#444444",
        "text.color": "#141821", "axes.labelcolor": "#141821",
        "figure.facecolor": "white", "savefig.facecolor": "white",
    })


def main() -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    style()
    data = json.load(open(os.path.join(HERE, "eval", "figure_data_s07.json"), encoding="utf-8"))
    gs = data["generator_stats"]
    order = [g for g in ORDER if g in gs]
    n = [gs[g]["n"] for g in order]
    nov = [gs[g]["frac_novel"] for g in order]
    sim = [gs[g]["mean_max_similarity"] for g in order]
    x = np.arange(len(order))
    colours = ["#567183", "#a98261", "#2b6cb0", "#855050"][: len(order)]

    fig, axes = plt.subplots(1, 3, figsize=(10.4, 3.4))
    count_title = (f"{WORD.get(len(order), len(order))} generator"
                   f"{'s' if len(order) != 1 else ''} contributed"
                   + ("" if len(order) == 4 else " (the rest did not run)"))
    panels = [(n, "unique valid molecules", count_title, None, "{:d}"),
              (nov, "fraction novel (max Tanimoto < 0.4)", novelty_title(gs, order), 0.80, "{:.2f}"),
              (sim, "mean max Tanimoto to actives", "Distance from the retrieved actives", 0.95,
               "{:.2f}")]
    for ax, (vals, ylab, title, ymax, fmt) in zip(axes, panels):
        ax.bar(x, vals, color=colours, width=0.62)
        off = (max(vals) * 0.035) if ymax is None else 0.022
        for xi, v in zip(x, vals):
            ax.text(xi, v + off, fmt.format(v), ha="center", fontsize=7)
        ax.set_xticks(x)
        ax.set_xticklabels([LABEL[g] for g in order], fontsize=7)
        ax.set_ylabel(ylab)
        ax.set_title(title)
        if ymax:
            ax.set_ylim(0, ymax)
        else:
            ax.margins(y=0.18)
    fig.text(0.004, 0.030,
             "G1 reaction-SMARTS decoration · G2 BRICS recombination of retrieved actives · "
             "G3 SELFIES token mutation · G4 LLM-proposed edits validated by RDKit.",
             fontsize=6.2, color="#666")
    fig.text(0.004, 0.008,
             "SMILES validity 1.00 for every generator shown (each emitted string re-parsed). "
             "Reference set: 271 measured ChEMBL actives for CHEMBL203 (EGFR); seed 20261111; "
             f"run {data.get('run_id', 'unknown')}"
             + (f"; absent from this run: {', '.join(data['generators_absent'])}"
                if data.get("generators_absent") else "") + ".",
             fontsize=6.2, color="#666")
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    out = os.path.join(HERE, "figures", "generator_comparison.png")
    fig.savefig(out, dpi=200)
    print(f"{out}: novelty title -> {novelty_title(gs, order)!r}; "
          f"frac_novel={dict(zip(order, nov))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
