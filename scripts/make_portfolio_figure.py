"""figures/deck/portfolio_molecules.png -- the eight selected molecules, drawn.

Each panel shows the structure with the maximum common substructure it shares with the seed
(erlotinib) in grey and everything else -- the modification -- in colour, plus the numbers the
ledger holds for that molecule. Nothing here is recomputed: scores, flags and origins are read
from the campaign run's answer file, so a panel cannot disagree with the claims ledger.

    python scripts/make_portfolio_figure.py [--run RUN_ID]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_NAME = "erlotinib"
SEED = "C#Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1"
GEN_SHORT = {"G1_rule_decorate": "G1 rule-decorate", "G2_brics_recombine": "G2 BRICS",
             "G3_selfies_mutate": "G3 SELFIES", "G4_llm_edits": "G4 LLM edit"}
GEN_COLOUR = {"G1_rule_decorate": (0.34, 0.44, 0.51), "G2_brics_recombine": (0.66, 0.51, 0.38),
              "G3_selfies_mutate": (0.17, 0.42, 0.69), "G4_llm_edits": (0.52, 0.31, 0.31)}


def pick_run(root: str, run_id: str | None) -> str:
    """The campaign run to draw: the one named, else the richest S08 run on disk."""
    if run_id:
        return run_id
    best = None
    suite = os.path.join(root, "eval", "final_suite.json")
    candidates = []
    if os.path.exists(suite):
        with open(suite, encoding="utf-8") as fh:
            candidates += [r["run_id"] for r in json.load(fh)["results"] if r["id"] == "S08"]
    import glob
    candidates += [os.path.basename(p)[:-len(".answer.json")]
                   for p in glob.glob(os.path.join(root, "runs", "*.answer.json"))]
    for rid in candidates:
        path = os.path.join(root, "runs", rid + ".answer.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            ans = json.load(fh)
        sel = [c for c in (ans.get("candidates") or []) if c.get("selected")]
        if not sel:
            continue
        docked = sum(1 for c in sel if (c.get("scores") or {}).get("vina_score") is not None)
        score = (len(sel), docked)
        if best is None or score > best[0]:
            best = (score, rid)
    if best is None:
        raise SystemExit("no run with a selected portfolio found under runs/")
    return best[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None)
    ap.add_argument("--out", default="figures/deck/portfolio_molecules.png")
    args = ap.parse_args(argv)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    from rdkit import Chem, RDLogger
    from rdkit.Chem import AllChem, Draw, rdFMCS
    from rdkit.Chem.Draw import rdMolDraw2D
    RDLogger.DisableLog("rdApp.*")

    run_id = pick_run(HERE, args.run)
    with open(os.path.join(HERE, "runs", run_id + ".answer.json"), encoding="utf-8") as fh:
        ans = json.load(fh)
    sel = [c for c in (ans.get("candidates") or []) if c.get("selected")]
    sel.sort(key=lambda c: c.get("rank") or 99)
    if not sel:
        raise SystemExit(f"run {run_id} has no selected candidates")

    seed = Chem.MolFromSmiles(SEED)
    panels = [{"mol": seed, "title": f"{SEED_NAME} (seed)", "sub": "the molecule the campaign "
                                                                   "started from", "origin": None,
               "highlight": [], "bonds": []}]
    for c in sel:
        m = Chem.MolFromSmiles(c["smiles"])
        if m is None:
            continue
        # Maximum common substructure with the seed: atoms NOT in it are the modification.
        mcs = rdFMCS.FindMCS([seed, m], timeout=10, ringMatchesRingOnly=True,
                             completeRingsOnly=False)
        common = m.GetSubstructMatch(Chem.MolFromSmarts(mcs.smartsString)) if mcs.smartsString \
            else ()
        changed = [a.GetIdx() for a in m.GetAtoms() if a.GetIdx() not in common]
        bonds = [b.GetIdx() for b in m.GetBonds()
                 if b.GetBeginAtomIdx() in changed or b.GetEndAtomIdx() in changed]
        sc = c.get("scores") or {}
        pr = c.get("properties") or {}
        flags = c.get("flags") or []
        alerts = "none" if not flags else ", ".join(str(f) for f in flags[:2])
        vina = sc.get("vina_score")
        sub = (f"QSAR pChEMBL {sc.get('qsar_pchembl', 'n/a')}"
               f"   Vina {vina if vina is not None else 'not docked'}\n"
               f"SA {pr.get('SAscore', 'n/a')}   QED {pr.get('QED', 'n/a')}   "
               f"alerts: {alerts}")
        panels.append({"mol": m, "title": f"{c['cand_id']} · {GEN_SHORT.get(c['origin'], c['origin'])}",
                       "sub": sub, "origin": c["origin"], "highlight": changed, "bonds": bonds,
                       "mcs_atoms": len(common)})

    ncols, nrows = 3, 3
    fig, axes = plt.subplots(nrows, ncols, figsize=(12.6, 13.6),
                             gridspec_kw={"hspace": 0.34, "wspace": 0.06})
    for ax in axes.ravel():
        ax.axis("off")
    for ax, p in zip(axes.ravel(), panels):
        AllChem.Compute2DCoords(p["mol"])
        d = rdMolDraw2D.MolDraw2DCairo(620, 460)
        opts = d.drawOptions()
        opts.clearBackground = False
        opts.bondLineWidth = 2
        colour = GEN_COLOUR.get(p["origin"], (0.17, 0.42, 0.69))
        rdMolDraw2D.PrepareAndDrawMolecule(
            d, p["mol"], highlightAtoms=p["highlight"], highlightBonds=p["bonds"],
            highlightAtomColors={i: colour for i in p["highlight"]},
            highlightBondColors={i: colour for i in p["bonds"]})
        d.FinishDrawing()
        png = d.GetDrawingText()
        import io
        import matplotlib.image as mpimg
        img = mpimg.imread(io.BytesIO(png), format="png")
        ax.imshow(img)
        ax.set_title(p["title"], fontsize=10.5, color="#141821", pad=4)
        ax.text(0.5, -0.045, p["sub"], transform=ax.transAxes, ha="center", va="top",
                fontsize=8.2, color="#444", linespacing=1.5)

    fig.suptitle("Portfolio of the S08 campaign: what the funnel actually selected",
                 fontsize=13, y=0.985)
    fig.text(0.5, 0.955,
             "Coloured atoms are the modification relative to erlotinib (everything outside the "
             "maximum common substructure); grey is the shared scaffold.",
             ha="center", fontsize=8.6, color="#555")
    fig.text(0.004, 0.012,
             f"Structures, generators, scores and alert flags read from runs/{run_id}.answer.json "
             f"-- the campaign's own claims ledger, not recomputed here. Vina scores on this "
             f"receptor are reported with the enrichment measured for it "
             f"(docs/docking_validation_table.md);\nQSAR values are PREDICTED with a conformal "
             f"interval and an applicability-domain verdict. 'not docked' means the campaign "
             f"docked only its top-ranked subset.",
             fontsize=7.2, color="#666", linespacing=1.5)
    fig.text(0.004, 0.012, "", fontsize=1)
    fig.tight_layout(rect=(0, 0.045, 1, 0.945))
    out = os.path.join(HERE, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=200)
    print(f"{args.out}: {len(panels) - 1} portfolio molecules + seed, from run {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
