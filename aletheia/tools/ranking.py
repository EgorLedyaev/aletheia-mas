"""Multi-objective ranking, diversity selection and portfolio arithmetic.

Three layers, deliberately kept separate so a reader can see which part is arithmetic and which
part is an assumption:

  1. `pareto_front`     pure arithmetic -- non-dominated sorting over the chosen objectives.
  2. `butina_clusters`  pure arithmetic -- Taylor-Butina clustering on Morgan fingerprints.
  3. `portfolio`        assumption-driven -- maps scores to per-candidate hit probabilities with
                        an explicit, uncalibrated transform and reports P(>=1 hit) twice: once
                        assuming independence, once assuming candidates inside a cluster fail
                        together. The gap between the two numbers is the honest uncertainty.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem
from rdkit.ML.Cluster import Butina

VERSION = "1.0"


def pareto_front(rows: List[Dict[str, Any]], objectives: Dict[str, str]) -> Dict[str, Any]:
    """Non-dominated sorting. `objectives` maps key -> 'max' or 'min'. Rows missing a key are skipped."""
    keys = [k for k in objectives if any(r.get(k) is not None for r in rows)]
    usable = [r for r in rows if all(r.get(k) is not None for k in keys)]
    if not usable or not keys:
        return {"objectives_used": keys, "n_usable": len(usable), "fronts": [], "front_of": {}}
    sign = {k: (1.0 if objectives[k] == "max" else -1.0) for k in keys}
    V = np.array([[sign[k] * float(r[k]) for k in keys] for r in usable], dtype=float)
    n = len(usable)
    front_of = [None] * n
    remaining = set(range(n))
    fronts: List[List[int]] = []
    while remaining:
        cur = []
        for i in remaining:
            dominated = False
            for j in remaining:
                if i == j:
                    continue
                if np.all(V[j] >= V[i]) and np.any(V[j] > V[i]):
                    dominated = True
                    break
            if not dominated:
                cur.append(i)
        if not cur:
            cur = list(remaining)
        for i in cur:
            front_of[i] = len(fronts)
        fronts.append(cur)
        remaining -= set(cur)
    return {"objectives_used": keys, "n_usable": n, "n_fronts": len(fronts),
            "fronts": [[usable[i]["cand_id"] for i in f] for f in fronts],
            "front_of": {usable[i]["cand_id"]: front_of[i] for i in range(n)},
            "method": "non-dominated sorting (exact, O(n^2))"}


def butina_clusters(smiles_list: List[str], cutoff: float = 0.35, radius: int = 2,
                    n_bits: int = 2048) -> Dict[str, Any]:
    """Taylor-Butina clustering at a Tanimoto distance cut-off."""
    gen = AllChem.GetMorganGenerator(radius=radius, fpSize=n_bits)
    fps, keep = [], []
    for i, s in enumerate(smiles_list):
        m = Chem.MolFromSmiles(s)
        if m is None:
            continue
        fps.append(gen.GetFingerprint(m))
        keep.append(i)
    if not fps:
        return {"n_clusters": 0, "clusters": [], "labels": {}}
    dists = []
    for i in range(1, len(fps)):
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
        dists.extend(1.0 - np.asarray(sims))
    cl = Butina.ClusterData(dists, len(fps), cutoff, isDistData=True)
    labels = {}
    for ci, cluster in enumerate(cl):
        for idx in cluster:
            labels[smiles_list[keep[idx]]] = ci
    return {"n_clusters": len(cl), "cutoff_tanimoto_distance": cutoff,
            "cluster_sizes": sorted((len(c) for c in cl), reverse=True),
            "clusters": [[smiles_list[keep[i]] for i in c] for c in cl],
            "labels": labels, "n_molecules": len(fps),
            "method": f"Taylor-Butina on Morgan r={radius} {n_bits}-bit fingerprints"}


def _p_hit(score: Optional[float], kind: str) -> float:
    """Fallback map used only when no fitted calibrator exists. Uncalibrated by construction."""
    if score is None:
        return 0.05
    if kind == "qsar_pchembl":           # pChEMBL 5 -> 0.05, 9 -> 0.45
        return float(np.clip(0.05 + (score - 5.0) * 0.10, 0.02, 0.45))
    if kind == "vina_score":             # -6 -> 0.05, -11 -> 0.40
        return float(np.clip(0.05 + (-score - 6.0) * 0.07, 0.02, 0.40))
    return 0.05


_CALIB_CACHE: Dict[str, Any] = {}


def _load_calibrator(target_id: Optional[str] = None,
                     model_dir: str = "models") -> Optional[Dict[str, Any]]:
    """Load a fitted hit-probability calibrator (scripts/calibrate_hit.py), if one exists."""
    import glob
    import pickle
    key = target_id or "*"
    if key in _CALIB_CACHE:
        return _CALIB_CACHE[key]
    paths = (glob.glob(os.path.join(model_dir, f"hit_calibrator_{target_id}.pkl"))
             if target_id else glob.glob(os.path.join(model_dir, "hit_calibrator_*.pkl")))
    bundle = None
    if len(paths) == 1:
        try:
            with open(paths[0], "rb") as fh:
                bundle = pickle.load(fh)
            bundle["path"] = paths[0]
        except Exception:
            bundle = None
    _CALIB_CACHE[key] = bundle
    return bundle


def _platt(params, x):
    a, b = params
    return float(1.0 / (1.0 + np.exp(-(a * x + b))))


def _calibrated_p(bundle, pred) -> Optional[float]:
    if bundle is None or pred is None:
        return None
    if bundle["kind"] == "platt" and bundle.get("params"):
        return _platt(bundle["params"], float(pred))
    try:
        return float(bundle["model"].predict([float(pred)])[0])
    except Exception:
        return None


def portfolio(candidates: List[Dict[str, Any]], k: int = 8, cutoff: float = 0.35,
              score_key: str = "qsar_pchembl", target_id: Optional[str] = None,
              require_in_domain: bool = True) -> Dict[str, Any]:
    """Greedy diversity-aware selection; reports P(>=1 hit) under two correlation assumptions."""
    rows = [c for c in candidates if c.get("smiles")]
    if not rows:
        return {"selected": [], "k": k}
    smis = [c["smiles"] for c in rows]
    clus = butina_clusters(smis, cutoff=cutoff)
    labels = clus["labels"]
    calib = _load_calibrator(target_id)
    probs: Dict[str, float] = {}
    no_prob: List[str] = []
    for c in rows:
        sc = (c.get("scores") or {}).get(score_key)
        ad = (c.get("properties") or {}).get("qsar_applicability")
        out_of_domain = require_in_domain and ad == "OUT_OF_DOMAIN"
        if out_of_domain:
            # Pre-registered: no probability is emitted outside the model's applicability domain.
            no_prob.append(c["cand_id"])
            probs[c["smiles"]] = 0.0
            continue
        if sc is None:
            sc = (c.get("scores") or {}).get("vina_score")
            probs[c["smiles"]] = _p_hit(sc, "vina_score")
        elif calib is not None and score_key == "qsar_pchembl":
            probs[c["smiles"]] = _calibrated_p(calib, sc) or 0.0
        else:
            probs[c["smiles"]] = _p_hit(sc, score_key)

    # greedy submodular selection of P(>=1 hit) under the cluster-correlation model
    selected: List[Dict[str, Any]] = []
    pool = list(rows)

    def p_any(sel: List[Dict[str, Any]]) -> float:
        best_per_cluster: Dict[Any, float] = {}
        for c in sel:
            cl = labels.get(c["smiles"], c["smiles"])
            best_per_cluster[cl] = max(best_per_cluster.get(cl, 0.0), probs[c["smiles"]])
        q = 1.0
        for p in best_per_cluster.values():
            q *= (1.0 - p)
        return 1.0 - q

    while pool and len(selected) < k:
        gains = [(p_any(selected + [c]) - p_any(selected), i) for i, c in enumerate(pool)]
        gains.sort(key=lambda t: (-t[0], t[1]))
        best_gain, bi = gains[0]
        selected.append(pool.pop(bi))
        if best_gain <= 0 and len(selected) >= 1:
            # no further correlated gain: keep filling by raw probability for breadth
            pool.sort(key=lambda c: -probs[c["smiles"]])
    p_corr = p_any(selected)
    q_ind = 1.0
    for c in selected:
        q_ind *= (1.0 - probs[c["smiles"]])
    p_ind = 1 - q_ind
    scored_probs = [probs[c["smiles"]] for c in selected if c["cand_id"] not in no_prob]
    p_full = max(scored_probs) if scored_probs else 0.0

    # Interval on the portfolio probability: refit-bootstrap replicates of the calibrator.
    ci_ind = ci_corr = ci_full = None
    if calib is not None and calib.get("boot_params") and score_key == "qsar_pchembl":
        scored = [c for c in selected if c["cand_id"] not in no_prob]
        preds = [(c.get("scores") or {}).get(score_key) for c in scored]
        preds = [p for p in preds if p is not None]
        clusters = [labels.get(c["smiles"], c["smiles"]) for c in scored]
        vi, vc, vf = [], [], []
        for params in calib["boot_params"]:
            ps = [_platt(params, p) for p in preds]
            q = 1.0
            for p in ps:
                q *= (1.0 - p)
            vi.append(1 - q)
            vf.append(max(ps) if ps else 0.0)
            best: Dict[Any, float] = {}
            for cl, p in zip(clusters, ps):
                best[cl] = max(best.get(cl, 0.0), p)
            qc = 1.0
            for p in best.values():
                qc *= (1.0 - p)
            vc.append(1 - qc)
        vi.sort()
        vc.sort()
        vf.sort()
        if vi:
            ci_ind = [round(vi[int(0.025 * len(vi))], 4), round(vi[int(0.975 * len(vi))], 4)]
            ci_corr = [round(vc[int(0.025 * len(vc))], 4), round(vc[int(0.975 * len(vc))], 4)]
            ci_full = [round(vf[int(0.025 * len(vf))], 4), round(vf[int(0.975 * len(vf))], 4)]

    # Oracle disagreement, reported next to every probability this tool emits.
    rho = None
    pairs = [((c.get("scores") or {}).get("qsar_pchembl"), (c.get("scores") or {}).get("vina_score"))
             for c in rows]
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    if len(pairs) >= 5:
        try:
            from scipy.stats import spearmanr
            rho = round(float(spearmanr([a for a, _ in pairs], [b for _, b in pairs]).statistic), 4)
        except Exception:
            rho = None

    if calib is not None:
        model_note = (f"{calib['kind']} calibrator fitted on the {calib.get('n_cal')}-molecule "
                      f"scaffold-split calibration fold; test-fold ECE {calib.get('ece_test')}")
        if not calib.get("criterion_met", False):
            model_note += (" -- ABOVE the pre-registered 0.10 threshold, so this probability is a "
                           "diagnostic, not a headline number")
    else:
        model_note = ("no fitted calibrator found; falling back to an uncalibrated monotone map "
                      "from score to P(hit)")
    warning = ("P(>=1 hit) is a model-derived quantity, not a measured hit rate. The two rows "
               "bracket the correlation assumption; the truth lies between them.")
    if rho is not None:
        warning += (f" The two oracles disagree on this candidate set (Spearman rho={rho} "
                    f"between the activity model and docking), so neither ordering is confirmed "
                    f"by the other.")
    return {"k": k, "n_candidates": len(rows),
            "selected": [{"cand_id": c["cand_id"], "smiles": c["smiles"],
                          "p_hit_assumed": (None if c["cand_id"] in no_prob
                                            else round(probs[c["smiles"]], 4)),
                          "cluster": labels.get(c["smiles"])} for c in selected],
            "n_clusters_represented": len({labels.get(c["smiles"]) for c in selected}),
            "n_without_probability_out_of_domain": len([c for c in selected
                                                        if c["cand_id"] in no_prob]),
            "p_at_least_one_hit_independent": round(p_ind, 4),
            "p_at_least_one_hit_independent_ci95": ci_ind,
            "p_at_least_one_hit_cluster_correlated": round(p_corr, 4),
            "p_at_least_one_hit_fully_correlated": round(p_full, 4),
            "p_at_least_one_hit_cluster_correlated_ci95": ci_corr,
            "p_at_least_one_hit_fully_correlated_ci95": ci_full,
            "oracle_disagreement_spearman": rho,
            "calibration": {"source": (calib or {}).get("path"),
                            "method": (calib or {}).get("kind"),
                            "ece_test": (calib or {}).get("ece_test"),
                            "criterion_met": bool((calib or {}).get("criterion_met", False)),
                            "hit_definition": f"measured pChEMBL >= {(calib or {}).get('hit_cut')}"
                            if calib else None},
            "score_key": score_key, "clustering": {k_: clus[k_] for k_ in
                                                   ("n_clusters", "cutoff_tanimoto_distance",
                                                    "cluster_sizes", "method")},
            "probability_model": model_note,
            "caveat": warning}


def register(registry, config):
    t = registry.tool
    t("ranking.pareto_front", VERSION, license="BSD-3-Clause", default_tag="COMPUTED",
      schema={"rows": "list[dict]", "objectives": "dict"})(pareto_front)
    t("ranking.butina_clusters", VERSION, license="BSD-3-Clause (RDKit)", default_tag="COMPUTED",
      schema={"smiles_list": "list[str]", "cutoff": "float"})(butina_clusters)
    t("ranking.portfolio", VERSION, license="BSD-3-Clause", default_tag="COMPUTED",
      schema={"candidates": "list[dict]", "k": "int"})(portfolio)
    return registry
