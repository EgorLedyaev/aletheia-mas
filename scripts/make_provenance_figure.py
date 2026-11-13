"""figures/deck/provenance_architecture.png -- the one-slide statement of what we built.

Left: the pipeline every tool-calling chemistry agent runs, in which the model's prose is the
final artefact and nothing stands between a plausible number and the reader. Right: ours, in which
the reporter can only print a value by rendering an Evidence object and a verifier re-scans the
finished answer, so an unresolvable numeric token withholds the answer instead of shipping it.

Counts in the right-hand column are read from the measured files, never typed in.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FG, DIM, ACC, BAD, OK = "#141821", "#5d6675", "#2b6cb0", "#b4443c", "#2f7d52"


def measured():
    out = {}
    p = os.path.join(HERE, "eval", "baseline_study.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            s = json.load(fh)["summary"]
        out["mas_cov"] = s["MAS_aletheia"]["mean_numeric_coverage"]
        out["b3_cov"] = s["B3_single_agent_ledger"]["mean_numeric_coverage"]
        out["mas_bad_ids"] = s["MAS_aletheia"]["identifiers_nonexistent"]
        out["b2_bad_ids"] = s["B2_single_agent"]["identifiers_nonexistent"]
    p = os.path.join(HERE, "eval", "deck_stats.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            out.update(json.load(fh))
    return out


def main() -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    m = measured()
    fig, ax = plt.subplots(figsize=(13.0, 7.0))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    def box(x, y, w, h, text, fc, ec, fontsize=9.2, weight="normal", tc=FG):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=1.2",
                                    linewidth=1.1, facecolor=fc, edgecolor=ec, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize,
                color=tc, zorder=3, linespacing=1.45, weight=weight)

    def arrow(x, y0, y1, colour=DIM):
        ax.add_patch(FancyArrowPatch((x, y0), (x, y1), arrowstyle="-|>", mutation_scale=13,
                                     linewidth=1.1, color=colour, zorder=1))

    ax.text(24, 95.5, "The usual tool-calling agent", ha="center", fontsize=12.5, weight="semibold")
    ax.text(74, 95.5, "Aletheia", ha="center", fontsize=12.5, weight="semibold", color=ACC)
    ax.text(24, 91.6, "ChemCrow-style, DrugAgent-style, autonomous loops", ha="center",
            fontsize=8.4, color=DIM)
    ax.text(74, 91.6, "the ledger is the product, not the agent count", ha="center",
            fontsize=8.4, color=DIM)

    left = [("user request", "#eef0f3", "#c3c8d2"),
            ("LLM plans and calls tools", "#eef0f3", "#c3c8d2"),
            ("tool results land in the prompt", "#eef0f3", "#c3c8d2"),
            ("the model writes the answer", "#fbeceb", BAD),
            ("numbers, identifiers and caveats\nare whatever the prose says", "#fbeceb", BAD)]
    y = 82
    for i, (t, fc, ec) in enumerate(left):
        box(6, y, 36, 8.2, t, fc, ec, tc=BAD if ec == BAD else FG)
        if i < len(left) - 1:
            arrow(24, y - 0.4, y - 4.0)
        y -= 12.4
    box(6, y - 2.0, 36, 9.6,
        "Nothing checks whether a printed value\ncame from a tool run. A wrong number costs\n"
        "a synthesis, an assay, a quarter.",
        "#fbeceb", BAD, fontsize=8.8, tc=BAD)

    right = [("user request", "#eef0f3", "#c3c8d2"),
             ("safety gate — deterministic lexicon,\nfail-closed, before any tool runs",
              "#eaf1f8", ACC),
             ("typed tool registry — every call\nversioned, hashed, cached", "#eaf1f8", ACC),
             ("claims ledger — each value becomes\nEvidence: tool, version, params, source, date",
              "#eaf1f8", ACC),
             ("reporter can only print by rendering\nan Evidence object", "#eaf1f8", ACC),
             ("blocking verifier — every numeric token\nmust resolve to a claim, or the answer "
              "is withheld", "#e8f3ec", OK)]
    y = 82
    for i, (t, fc, ec) in enumerate(right):
        box(56, y, 38, 8.2, t, fc, ec, fontsize=8.8,
            weight="semibold" if i == len(right) - 1 else "normal")
        if i < len(right) - 1:
            arrow(75, y - 0.4, y - 4.0, ACC)
        y -= 12.4
    cov = m.get("mas_cov")
    b3 = m.get("b3_cov")
    bad = m.get("mas_bad_ids")
    b2bad = m.get("b2_bad_ids")
    measured_txt = (f"{cov:.2f} of published numbers resolve to a tool call\n"
                    f"({b3:.2f} for the same ledger without the verifier)\n"
                    f"{bad} nonexistent identifiers, vs {b2bad} for one tool-using agent"
                    if cov is not None else "run scripts/bench_baselines.py for the measured rates")
    box(56, y - 2.0, 38, 9.6, measured_txt, "#e8f3ec", OK, fontsize=8.6, tc=FG)

    ax.add_patch(FancyBboxPatch((49.4, 6), 1.2, 84, boxstyle="round,pad=0.1", linewidth=0,
                                facecolor="#e3e6ea", zorder=0))
    scen = m.get("scenarios_passed")
    tot = m.get("scenarios_total")
    foot = ("Measured on 24 graded queries with ground truth recomputed at run time "
            "(eval/baseline_study.json)")
    if scen:
        foot += f"; {scen}/{tot} scenarios pass machine-checked invariants (eval/final_suite.json)"
    fig.text(0.5, 0.018, foot + ".", ha="center", fontsize=7.6, color=DIM)
    out = os.path.join(HERE, "figures", "deck", "provenance_architecture.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=200, facecolor="white")
    print(f"figures/deck/provenance_architecture.png: coverage {cov} vs {b3}, bad ids {bad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
