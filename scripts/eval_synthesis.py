"""Synthetic-feasibility triage for the portfolio: which bond would a chemist make last?

For each selected molecule this proposes the most likely final bond-forming step by matching
retrosynthetic SMARTS patterns that the generators themselves can produce (amide coupling,
Suzuki-type biaryl, SNAr on an activated heteroarene, reductive amination, sulfonamide, ether).
It is a **heuristic triage, not a retrosynthesis**: no route search, no reagent prediction, no
supplier lookup. Buildability is expressed as a traffic light from the matched disconnection and
the RDKit SA score, and the building blocks named are the fragments either side of the proposed
disconnection -- their commercial availability is NOT checked, because no catalogue is reachable
from this environment.

    python scripts/eval_synthesis.py [--run RUN_ID]  ->  docs/synthesis_feasibility.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (name, retrosynthetic SMARTS, plausible starting materials, default light)
DISCONNECTIONS = [
    ("amide coupling",
     "[C;!$(C=O)][CX3](=O)[NX3;H1,H2][#6]",
     "acid + amine, HATU/EDC",
     "green"),
    ("sulfonamide formation",
     "[#6][SX4](=O)(=O)[NX3;H1,H2]",
     "sulfonyl chloride + amine",
     "green"),
    ("SNAr on an activated heteroarene",
     "[nX2,$(c1ncncc1),$(c1ncccn1)][c;$(c1ncncc1),$(c1ccncn1)][NX3;H1][c]",
     "chloro-heteroarene + aniline",
     "green"),
    ("Buchwald-Hartwig / SNAr C-N",
     "[c][NX3;H1][c]",
     "aryl halide + aniline, Pd or thermal SNAr",
     "yellow"),
    ("Suzuki-type biaryl",
     "[c][c;$(c1ccccc1)]-[c;$(c1ccccc1)]",
     "aryl halide + boronic acid",
     "yellow"),
    ("Williamson ether / alkylation",
     "[OX2]([#6;!$(C=O)])[#6;!$(C=O)]",
     "phenol/alcohol + alkyl halide",
     "green"),
    ("reductive amination",
     "[NX3;H0,H1]([#6])[CH2][#6]",
     "aldehyde + amine, NaBH(OAc)3",
     "yellow"),
]
# Motifs that make a molecule hard to make or hard to keep. The generators -- SELFIES mutation
# especially -- produce these happily, and they are exactly what a medicinal chemist spots in the
# first two seconds of looking at a proposal, so they are flagged here rather than left to the eye.
HARD_FEATURES = [
    ("strained or unusual ring", "[r3,r4]"),
    ("macrocycle or large ring", "[r{8-}]"),
    ("allene / cumulated diene", "[CX3]=[CX2]=[CX3]"),
    ("ynol ether (alkoxy alkyne)", "[OX2][CX2]#[CX2]"),
    ("enol ether (acid-labile)", "[OX2;!$(O[CX3]=O)][CX3]=[CX3]"),
    ("ketene / cumulated C=C=O", "C=C=O"),
]


def assess(smiles: str):
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Descriptors
    RDLogger.DisableLog("rdApp.*")
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return None
    hits = []
    for name, smarts, blocks, light in DISCONNECTIONS:
        patt = Chem.MolFromSmarts(smarts)
        if patt is not None and m.HasSubstructMatch(patt):
            hits.append((name, blocks, light))
    hard = [n for n, sm in HARD_FEATURES
            if Chem.MolFromSmarts(sm) is not None and m.HasSubstructMatch(Chem.MolFromSmarts(sm))]
    try:
        from rdkit.Chem import RDConfig
        sys.path.append(os.path.join(RDConfig.RDContribDir, "SA_Score"))
        import sascorer
        sa = round(float(sascorer.calculateScore(m)), 2)
    except Exception:
        sa = None
    return {"disconnections": hits, "hard_features": hard, "sa": sa,
            "rings": Descriptors.RingCount(m), "heavy": m.GetNumHeavyAtoms()}


def light_for(info, sa_from_run):
    sa = sa_from_run if sa_from_run is not None else info["sa"]
    if not info["disconnections"]:
        return "red", "no routine disconnection matched"
    worst = "green" if any(h[2] == "green" for h in info["disconnections"]) else "yellow"
    labile = [f for f in info["hard_features"] if "labile" in f or "allene" in f or "ynol" in f]
    if info["hard_features"]:
        worst = "yellow" if worst == "green" else "red"
    if labile:
        worst = "red" if len(labile) > 1 else worst
    if sa is not None and sa >= 4.0:
        worst = "yellow" if worst == "green" else "red"
    reason = []
    if info["hard_features"]:
        reason.append("; ".join(info["hard_features"]))
    if sa is not None and sa >= 4.0:
        reason.append(f"SA {sa} >= 4")
    return worst, ("routine disconnection available" if not reason else "; ".join(reason))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None)
    ap.add_argument("--out", default="docs/synthesis_feasibility.md")
    args = ap.parse_args(argv)
    sys.path.insert(0, os.path.join(HERE, "scripts"))
    from make_portfolio_figure import pick_run                       # noqa: E402
    run_id = pick_run(HERE, args.run)
    with open(os.path.join(HERE, "runs", run_id + ".answer.json"), encoding="utf-8") as fh:
        ans = json.load(fh)
    sel = [c for c in (ans.get("candidates") or []) if c.get("selected")]
    sel.sort(key=lambda c: c.get("rank") or 99)

    rows, counts = [], {"green": 0, "yellow": 0, "red": 0}
    for c in sel:
        info = assess(c["smiles"])
        if info is None:
            continue
        sa_run = (c.get("properties") or {}).get("SAscore")
        light, why = light_for(info, sa_run)
        counts[light] += 1
        first = info["disconnections"][0] if info["disconnections"] else ("none matched", "-", "")
        rows.append({"id": c["cand_id"], "origin": c["origin"], "smiles": c["smiles"],
                     "reaction": first[0], "blocks": first[1],
                     "alternatives": [d[0] for d in info["disconnections"][1:3]],
                     "sa": sa_run if sa_run is not None else info["sa"],
                     "light": light, "why": why, "hard": info["hard_features"]})

    lines = ["# Synthetic feasibility of the portfolio — heuristic triage", "",
             f"Generated by `scripts/eval_synthesis.py` from `runs/{run_id}.answer.json`.", "",
             "**What this is.** For each selected molecule, the most likely *final* bond-forming "
             "step, found by matching retrosynthetic SMARTS for the reaction classes the "
             "generators can actually produce. **What this is not:** a retrosynthesis, a route, "
             "a reagent recommendation, or a purchasability check. No catalogue is reachable from "
             "this environment, so the building blocks below are the fragments either side of the "
             "proposed disconnection — they are *plausible* starting materials, not verified "
             "commercial ones. A chemist should read the traffic light as "
             "\"worth a retrosynthesis\" versus \"look again\".", "",
             "| Candidate | Generator | Proposed final step | Plausible building blocks "
             "(availability NOT verified) | SA score | Traffic light | Why |",
             "|---|---|---|---|---|---|---|"]
    emoji = {"green": "🟢 green", "yellow": "🟡 yellow", "red": "🔴 red"}
    for r in rows:
        alt = f" (also: {', '.join(r['alternatives'])})" if r["alternatives"] else ""
        lines.append(f"| `{r['id']}` | {r['origin'].split('_')[0]} | {r['reaction']}{alt} | "
                     f"{r['blocks']} | {r['sa']} | {emoji[r['light']]} | {r['why']} |")
    lines += ["",
              f"**Summary.** {counts['green']} green, {counts['yellow']} yellow, "
              f"{counts['red']} red out of {len(rows)} selected molecules. ",
              "",
              "The SA score is RDKit's synthetic-accessibility estimate (1 = easy, 10 = hard) and "
              "is already one of the funnel's gate criteria (<= 6.0), so a red light here is "
              "usually a *ring system* problem rather than a decoration problem — which is what "
              "the SELFIES mutation generator is expected to produce and why its output is "
              "reported separately in `docs/evaluation_report.md`.", "",
              "| SMILES (for a chemist to paste into a retrosynthesis tool) |", "|---|"]
    for r in rows:
        lines.append(f"| `{r['id']}` `{r['smiles']}` |")
    path = os.path.join(HERE, args.out)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    json.dump({"run_id": run_id, "rows": rows, "counts": counts},
              open(os.path.join(HERE, "eval", "synthesis_feasibility.json"), "w",
                   encoding="utf-8"), indent=1)
    print(f"{args.out}: {len(rows)} molecules, {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
