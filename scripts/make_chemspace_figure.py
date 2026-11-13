"""figures/deck/chemical_space.png -- where the generated candidates sit relative to the actives.

Morgan fingerprints (ECFP4, 2048 bits) for three populations: the measured ChEMBL actives used to
train the activity model, the campaign's generated candidates coloured by the generator that made
them, and the molecules the ranker selected. Projection by PCA on the Jaccard-complement space
(deterministic) with t-SNE as an option. Butina clusters are drawn as hulls so "diverse portfolio"
can be checked by eye rather than asserted.

    python scripts/make_chemspace_figure.py [--run RUN_ID] [--method pca|tsne]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN_SHORT = {"G1_rule_decorate": "G1 rule-decorate", "G2_brics_recombine": "G2 BRICS",
             "G3_selfies_mutate": "G3 SELFIES", "G4_llm_edits": "G4 LLM edit"}
GEN_COLOUR = {"G1_rule_decorate": "#567183", "G2_brics_recombine": "#a98261",
              "G3_selfies_mutate": "#2b6cb0", "G4_llm_edits": "#855050"}


def style():
    import matplotlib as mpl
    mpl.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 200, "font.size": 9, "axes.titlesize": 10.5,
        "axes.labelsize": 9, "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8,
        "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#444444",
        "axes.linewidth": 0.8, "text.color": "#141821", "figure.facecolor": "white",
        "savefig.facecolor": "white"})


def cached_actives(target="CHEMBL203", n_expected=271):
    for fp in sorted(glob.glob(os.path.join(HERE, "cache", "tools", "chembl_activities", "*"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                blob = json.load(fh)
        except Exception:
            continue
        data = blob.get("data", blob)
        acts = data.get("activities") if isinstance(data, dict) else None
        if acts and len(acts) == n_expected and acts[0].get("target_chembl_id") == target:
            return [a.get("smiles") or a.get("canonical_smiles") for a in acts]
    return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None)
    ap.add_argument("--method", default="pca", choices=["pca", "tsne"])
    ap.add_argument("--out", default="figures/deck/chemical_space.png")
    args = ap.parse_args(argv)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from rdkit import Chem, DataStructs, RDLogger
    from rdkit.Chem import rdFingerprintGenerator
    from rdkit.ML.Cluster import Butina
    RDLogger.DisableLog("rdApp.*")
    style()

    sys.path.insert(0, os.path.join(HERE, "scripts"))
    from make_portfolio_figure import pick_run                      # noqa: E402
    run_id = pick_run(HERE, args.run)
    with open(os.path.join(HERE, "runs", run_id + ".answer.json"), encoding="utf-8") as fh:
        ans = json.load(fh)
    cands = ans.get("candidates") or []

    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    rows = []
    for smi in cached_actives():
        m = Chem.MolFromSmiles(smi or "")
        if m is not None:
            rows.append(("active", None, smi, gen.GetFingerprint(m)))
    for c in cands:
        m = Chem.MolFromSmiles(c["smiles"])
        if m is None:
            continue
        kind = "portfolio" if c.get("selected") else "candidate"
        rows.append((kind, c.get("origin"), c["smiles"], gen.GetFingerprint(m)))
    if not rows:
        raise SystemExit("nothing to plot")

    X = np.zeros((len(rows), 2048), dtype=np.uint8)
    for i, r in enumerate(rows):
        DataStructs.ConvertToNumpyArray(r[3], X[i])

    if args.method == "tsne":
        from sklearn.manifold import TSNE
        emb = TSNE(n_components=2, random_state=20261111, init="pca",
                   perplexity=min(30, max(5, len(rows) // 4))).fit_transform(X.astype(float))
        axis_label = "t-SNE dimension"
    else:
        from sklearn.decomposition import PCA
        p = PCA(n_components=2, random_state=20261111)
        emb = p.fit_transform(X.astype(float))
        var = p.explained_variance_ratio_
        axis_label = "principal component"

    kinds = np.array([r[0] for r in rows])
    origins = np.array([r[1] if r[1] else "" for r in rows])

    # Butina clustering over the candidates only, at the cutoff the ranker uses.
    cand_idx = np.where(kinds != "active")[0]
    fps = [rows[i][3] for i in cand_idx]
    dists = []
    for i in range(1, len(fps)):
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
        dists.extend(1 - s for s in sims)
    clusters = Butina.ClusterData(dists, len(fps), 0.35, isDistData=True) if len(fps) > 1 else []

    fig, ax = plt.subplots(figsize=(12.2, 6.8))
    m = kinds == "active"
    ax.scatter(emb[m, 0], emb[m, 1], s=16, c="#c9ced6", edgecolors="none", zorder=1,
               label=f"measured ChEMBL actives (n={int(m.sum())})")
    for g, colour in GEN_COLOUR.items():
        sel = (kinds == "candidate") & (origins == g)
        if sel.any():
            ax.scatter(emb[sel, 0], emb[sel, 1], s=34, c=colour, alpha=0.85, edgecolors="white",
                       linewidths=0.4, zorder=2,
                       label=f"{GEN_SHORT[g]} (n={int(sel.sum())})")
    for g, colour in GEN_COLOUR.items():
        sel = (kinds == "portfolio") & (origins == g)
        if sel.any():
            ax.scatter(emb[sel, 0], emb[sel, 1], s=230, c=colour, marker="*",
                       edgecolors="#141821", linewidths=0.9, zorder=4)
    ax.scatter([], [], s=200, marker="*", c="white", edgecolors="#141821", linewidths=0.9,
               label=f"selected into the portfolio (n={int((kinds == 'portfolio').sum())})")

    # cluster hulls, biggest first, so "diverse" is visible rather than claimed
    big = [c for c in sorted(clusters, key=len, reverse=True) if len(c) >= 4][:3]
    for k, cl in enumerate(big):
        pts = emb[[cand_idx[i] for i in cl]]
        if len(pts) >= 3:
            try:
                from scipy.spatial import ConvexHull
                h = ConvexHull(pts)
                ax.fill(pts[h.vertices, 0], pts[h.vertices, 1], facecolor="#2b6cb0", alpha=0.06,
                        edgecolor="#2b6cb0", linewidth=0.7, linestyle="--", zorder=0)
                cx = pts[:, 0].mean()
                cy = pts[:, 1].max()
                ax.annotate(f"cluster {k + 1}: {len(cl)} molecules", (cx, cy),
                            xytext=(0, 9 + 11 * k), textcoords="offset points", fontsize=7.2,
                            color="#2b6cb0", ha="center", va="bottom", zorder=5)
            except Exception:
                pass

    # Objective-space inset: the trade-off the ranker actually optimises. Chemical-space
    # coordinates have no "better" direction, so the Pareto front is drawn where it means
    # something -- predicted activity against docking score, for the molecules that have both.
    pts = []
    for c in cands:
        sc = c.get("scores") or {}
        q = sc.get("qsar_pchembl")
        v = sc.get("vina_score")
        if q is not None and v is not None:
            pts.append((float(q), float(v), bool(c.get("selected")), c.get("cand_id")))
    if len(pts) >= 4:
        axi = ax.inset_axes([0.055, 0.075, 0.27, 0.30], zorder=6)
        axi.set_facecolor("white")
        front = []
        for q, v, s, cid in pts:
            if not any((q2 >= q and v2 <= v and (q2, v2) != (q, v)) for q2, v2, _, _ in pts):
                front.append((q, v, s, cid))
        front.sort()
        axi.scatter([p[0] for p in pts], [p[1] for p in pts], s=16, c="#9aa4b2",
                    edgecolors="none", zorder=1)
        sel_pts = [p for p in pts if p[2]]
        axi.scatter([p[0] for p in sel_pts], [p[1] for p in sel_pts], s=70, marker="*",
                    c="#2b6cb0", edgecolors="#141821", linewidths=0.6, zorder=3)
        if len(front) >= 2:
            axi.plot([p[0] for p in front], [p[1] for p in front], color="#b4443c",
                     linewidth=1.1, linestyle="--", zorder=2,
                     label=f"Pareto front (n={len(front)})")
            axi.legend(frameon=False, fontsize=6.2, loc="lower left")
        axi.set_xlabel("predicted pChEMBL", fontsize=6.6, labelpad=1.5)
        axi.set_ylabel("Vina score (kcal/mol)", fontsize=6.6, labelpad=1.5)
        axi.tick_params(labelsize=6)
        axi.set_title(f"objective space: {len(pts)} docked candidates", fontsize=7.2, pad=3)
        for sp in ("top", "right"):
            axi.spines[sp].set_visible(False)
        axi.patch.set_alpha(1.0)
        for sp in ("left", "bottom"):
            axi.spines[sp].set_color("#9aa4b2")

    seed_smiles = next((c.get("parent") for c in cands if c.get("parent")), None)
    ax.set_xlabel(f"{axis_label} 1" + (f" ({var[0]*100:.1f}% variance)"
                                       if args.method == "pca" else ""))
    ax.set_ylabel(f"{axis_label} 2" + (f" ({var[1]*100:.1f}% variance)"
                                       if args.method == "pca" else ""))
    ax.set_title("Generated candidates against the measured actives they were designed from")
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    n_clusters = len(clusters)
    import textwrap
    note = (f"ECFP4 (Morgan radius 2, 2048 bits); {args.method.upper()} projection, seed "
            f"20261111. Candidates and portfolio from runs/{run_id}.answer.json; actives are the "
            f"271 ChEMBL records the activity model was fitted on. Butina clustering at Tanimoto "
            f"distance 0.35 -- the cutoff the ranker uses -- gives {n_clusters} clusters over "
            f"{len(cand_idx)} candidates; the {int((kinds == 'portfolio').sum())} selected "
            f"molecules are starred. A projection preserves neighbourhoods only approximately: "
            f"read it as a sanity check, not as a distance measurement. The inset shows the same "
            f"candidates in the objective space the ranker optimises; the dashed line is the "
            f"Pareto front over predicted activity and docking score, and a selected molecule "
            f"off the front is there for cluster diversity.")
    fig.text(0.004, 0.015, "\n".join(textwrap.wrap(note, 150)),
             fontsize=6.6, color="#666", linespacing=1.5, va="bottom")
    fig.tight_layout(rect=(0, 0.115, 0.80, 1))
    out = os.path.join(HERE, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=200)
    print(f"{args.out}: {int(m.sum())} actives, {len(cand_idx)} candidates, "
          f"{int((kinds == 'portfolio').sum())} selected, {n_clusters} Butina clusters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
