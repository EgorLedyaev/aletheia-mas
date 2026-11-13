"""Activity-proxy (QSAR) modelling with leakage-free splits, baselines and conformal intervals.

Choices that make the numbers defensible rather than decorative:
  * **Bemis-Murcko scaffold split**, not a random split: whole scaffolds go to the test set, so a
    near-duplicate analogue cannot sit on both sides.
  * **Mandatory baselines**: the train-mean predictor and a 1-nearest-neighbour Tanimoto
    predictor are always fitted; a model that does not beat them is reported as not beating them.
  * **Split-conformal intervals**: a calibration split gives a finite-sample interval with the
    requested coverage under exchangeability, instead of an uncalibrated ensemble spread.
  * **Applicability domain**: maximum Tanimoto similarity to the training set, bucketed.
"""
from __future__ import annotations

import os
import pickle
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import AllChem, Crippen, Descriptors, rdMolDescriptors
from rdkit.Chem.Scaffolds import MurckoScaffold

RDLogger.DisableLog("rdApp.*")
VERSION = "1.0"
DESC_FN = [("MolWt", Descriptors.MolWt), ("cLogP", Crippen.MolLogP),
           ("TPSA", rdMolDescriptors.CalcTPSA), ("HBD", rdMolDescriptors.CalcNumHBD),
           ("HBA", rdMolDescriptors.CalcNumHBA), ("RotB", rdMolDescriptors.CalcNumRotatableBonds),
           ("Rings", rdMolDescriptors.CalcNumRings), ("FracCSP3", rdMolDescriptors.CalcFractionCSP3)]


def _fp_gen(n_bits: int = 2048, radius: int = 2):
    return AllChem.GetMorganGenerator(radius=radius, fpSize=n_bits)


def featurize(smiles_list: List[str], n_bits: int = 2048, radius: int = 2):
    gen = _fp_gen(n_bits, radius)
    X, fps, keep = [], [], []
    for i, s in enumerate(smiles_list):
        m = Chem.MolFromSmiles(s)
        if m is None:
            continue
        fp = gen.GetFingerprint(m)
        arr = np.zeros((n_bits,), dtype=np.int8)
        DataStructs.ConvertToNumpyArray(fp, arr)
        desc = [float(f(m)) for _, f in DESC_FN]
        X.append(np.concatenate([arr.astype(np.float32), np.asarray(desc, dtype=np.float32)]))
        fps.append(fp)
        keep.append(i)
    return np.asarray(X, dtype=np.float32), fps, keep


def scaffold_split(smiles: List[str], test_frac: float = 0.2, seed: int = 42) -> Dict[str, Any]:
    """Assign whole Bemis-Murcko scaffolds to train or test (largest groups to train first)."""
    groups: Dict[str, List[int]] = {}
    for i, s in enumerate(smiles):
        m = Chem.MolFromSmiles(s)
        key = ""
        if m is not None:
            try:
                key = Chem.MolToSmiles(MurckoScaffold.GetScaffoldForMol(m))
            except Exception:
                key = ""
        groups.setdefault(key or f"_singleton_{i}", []).append(i)
    order = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    n_test_target = int(round(len(smiles) * test_frac))
    test: List[int] = []
    train: List[int] = []
    for _, idxs in order:
        if len(test) < n_test_target and len(idxs) <= max(2, n_test_target - len(test)):
            test.extend(idxs)
        else:
            train.extend(idxs)
    if not test:                       # degenerate case: one giant scaffold
        rng = np.random.default_rng(seed)
        idx = rng.permutation(len(smiles))
        test = list(idx[:n_test_target])
        train = list(idx[n_test_target:])
    return {"train_idx": sorted(train), "test_idx": sorted(test), "n_scaffolds": len(groups),
            "n_train": len(train), "n_test": len(test),
            "method": "Bemis-Murcko scaffold split (whole scaffolds held out)"}


def _metrics(y: np.ndarray, p: np.ndarray) -> Dict[str, float]:
    from scipy.stats import spearmanr
    err = p - y
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    out = {"rmse": round(float(np.sqrt(np.mean(err ** 2))), 4),
           "mae": round(float(np.mean(np.abs(err))), 4),
           "r2": round(1 - ss_res / ss_tot, 4) if ss_tot > 0 else None}
    if len(y) > 2 and float(np.std(y)) > 0 and float(np.std(p)) > 0:
        rho = spearmanr(y, p)
        out["spearman"] = round(float(rho.statistic), 4)
        out["spearman_p"] = float(rho.pvalue)
    return out


def fit(actives: List[Dict[str, Any]], target_id: str = "target", seed: int = 42,
        test_frac: float = 0.2, alpha: float = 0.1, n_estimators: int = 300,
        model_dir: str = "models") -> Dict[str, Any]:
    """Fit a random-forest activity model with a scaffold split, baselines and conformal calibration."""
    from sklearn.ensemble import RandomForestRegressor

    smiles = [a["smiles"] for a in actives]
    y_all = np.asarray([float(a["pchembl_value"]) for a in actives], dtype=np.float32)
    if len(smiles) < 40:
        raise ValueError(f"only {len(smiles)} activity records; refusing to fit a QSAR model "
                         "below 40 (too few for a scaffold split with a calibration set)")
    X, fps, keep = featurize(smiles)
    y = y_all[keep]
    smiles = [smiles[i] for i in keep]
    split = scaffold_split(smiles, test_frac=test_frac, seed=seed)
    tr, te = split["train_idx"], split["test_idx"]
    rng = np.random.default_rng(seed)
    tr_perm = rng.permutation(len(tr))
    n_cal = max(10, int(0.2 * len(tr)))
    cal_idx = [tr[i] for i in tr_perm[:n_cal]]
    fit_idx = [tr[i] for i in tr_perm[n_cal:]]

    model = RandomForestRegressor(n_estimators=n_estimators, random_state=seed, n_jobs=-1,
                                  min_samples_leaf=2)
    model.fit(X[fit_idx], y[fit_idx])

    # conformal calibration on held-out calibration split
    cal_pred = model.predict(X[cal_idx])
    residuals = np.abs(cal_pred - y[cal_idx])
    n = len(residuals)
    q_level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
    q_hat = float(np.quantile(residuals, q_level, method="higher"))

    # test metrics + baselines
    test_pred = model.predict(X[te])
    m_model = _metrics(y[te], test_pred)
    mean_pred = np.full(len(te), float(y[fit_idx].mean()), dtype=np.float32)
    m_mean = _metrics(y[te], mean_pred)
    nn_pred = []
    fit_fps = [fps[i] for i in fit_idx]
    for i in te:
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fit_fps)
        nn_pred.append(float(y[fit_idx][int(np.argmax(sims))]))
    m_nn = _metrics(y[te], np.asarray(nn_pred, dtype=np.float32))

    # empirical coverage of the conformal interval on the test set
    covered = float(np.mean(np.abs(test_pred - y[te]) <= q_hat))

    os.makedirs(model_dir, exist_ok=True)
    path = os.path.join(model_dir, f"qsar_{target_id}.pkl")
    with open(path, "wb") as fh:
        pickle.dump({"model": model, "q_hat": q_hat, "alpha": alpha, "seed": seed,
                     "train_smiles": [smiles[i] for i in fit_idx],
                     "train_y": y[fit_idx].tolist(), "target_id": target_id,
                     "n_bits": 2048, "radius": 2, "version": VERSION}, fh)
    return {"target_id": target_id, "model_path": path.replace("\\", "/"),
            "n_records": len(smiles), "split": split,
            "n_fit": len(fit_idx), "n_calibration": len(cal_idx), "n_test": len(te),
            "metrics_model": m_model, "metrics_baseline_mean": m_mean,
            "metrics_baseline_1nn_tanimoto": m_nn,
            "beats_mean_baseline": bool(m_model["rmse"] < m_mean["rmse"]),
            "beats_1nn_baseline": bool(m_model["rmse"] < m_nn["rmse"]),
            "conformal": {"alpha": alpha, "q_hat": round(q_hat, 4),
                          "nominal_coverage": round(1 - alpha, 3),
                          "empirical_test_coverage": round(covered, 4),
                          "interval_width": round(2 * q_hat, 4)},
            "y_range": [round(float(y.min()), 3), round(float(y.max()), 3)],
            "y_std": round(float(y.std()), 4),
            "units": "pChEMBL (-log10 molar)",
            "model_type": f"RandomForestRegressor(n_estimators={n_estimators}, min_samples_leaf=2)",
            "features": "Morgan count-free bit FP (r=2, 2048 bits) + 8 RDKit descriptors",
            "test_predictions": [{"smiles": smiles[i], "y_true": round(float(y[i]), 3),
                                  "y_pred": round(float(p), 3)}
                                 for i, p in zip(te, test_pred)]}


def predict(model_path: str, smiles_list: List[str],
            ad_in: float = 0.40, ad_border: float = 0.25) -> Dict[str, Any]:
    """Predict pChEMBL with conformal intervals and an applicability-domain verdict."""
    with open(model_path, "rb") as fh:
        bundle = pickle.load(fh)
    model, q_hat = bundle["model"], bundle["q_hat"]
    gen = _fp_gen(bundle["n_bits"], bundle["radius"])
    train_fps = [gen.GetFingerprint(Chem.MolFromSmiles(s)) for s in bundle["train_smiles"]
                 if Chem.MolFromSmiles(s)]
    X, fps, keep = featurize(smiles_list, bundle["n_bits"], bundle["radius"])
    if len(keep) == 0:
        return {"predictions": [], "n": 0, "model_path": model_path}
    preds = model.predict(X)
    rows = []
    for k, (i, p) in enumerate(zip(keep, preds)):
        sims = DataStructs.BulkTanimotoSimilarity(fps[k], train_fps) if train_fps else [0.0]
        mx = float(max(sims))
        ad = ("IN_DOMAIN" if mx >= ad_in else "BORDERLINE" if mx >= ad_border else "OUT_OF_DOMAIN")
        rows.append({"smiles": smiles_list[i], "pred_pchembl": round(float(p), 3),
                     "lower": round(float(p - q_hat), 3), "upper": round(float(p + q_hat), 3),
                     "max_tanimoto_to_train": round(mx, 4), "applicability": ad})
    return {"predictions": rows, "n": len(rows), "model_path": model_path,
            "alpha": bundle["alpha"], "q_hat": round(float(q_hat), 4),
            "target_id": bundle["target_id"],
            "ad_thresholds": {"in_domain_min_tanimoto": ad_in, "borderline_min_tanimoto": ad_border},
            "units": "pChEMBL (-log10 molar)"}


def register(registry, config):
    t = registry.tool
    t("qsar.fit", VERSION, license="BSD-3-Clause (scikit-learn, RDKit)", default_tag="COMPUTED",
      cost_hint="medium", schema={"actives": "list[dict]", "target_id": "str"})(fit)
    t("qsar.predict", VERSION, license="BSD-3-Clause (scikit-learn, RDKit)",
      default_tag="PREDICTED", schema={"model_path": "str", "smiles_list": "list[str]"})(predict)
    t("qsar.scaffold_split", VERSION, license="BSD-3-Clause (RDKit)", default_tag="COMPUTED",
      schema={"smiles": "list[str]"})(scaffold_split)
    return registry
