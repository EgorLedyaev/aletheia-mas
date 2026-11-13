"""W2: calibrate P(hit) and the portfolio's P(>=1 hit). Criteria: docs/preregistration.md W2.

A hit is a molecule whose measured pChEMBL against the target is >= 7.0 (pre-declared).

The system previously mapped a predicted pChEMBL to a hit probability with a hand-written linear
rule and multiplied those numbers together, producing portfolio probabilities near 0.96 that had
never been compared with an observed hit rate. This script fits a real calibrator on the
scaffold-split calibration fold, measures ECE and the Brier score on the held-out test fold, and
compares against that hand-written rule.

    python scripts/calibrate_hit.py
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pickle
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aletheia.tools.qsar_tools import featurize, scaffold_split   # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIT_CUT = 7.0


def legacy_p_hit(pred):
    """The uncalibrated map currently in aletheia/tools/ranking.py."""
    return np.clip(0.05 + (np.asarray(pred) - 5.0) * 0.10, 0.02, 0.45)


def load_actives(target_id, n_expected):
    for fp in sorted(glob.glob(os.path.join(HERE, "cache", "tools", "chembl_activities", "*"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                blob = json.load(fh)
        except Exception:
            continue
        data = blob.get("data", blob)
        acts = data.get("activities") if isinstance(data, dict) else None
        if not acts or len(acts) != n_expected:
            continue
        if acts[0].get("target_chembl_id") != target_id:
            continue
        return acts, os.path.basename(fp)
    raise SystemExit(f"no cached activity set of size {n_expected} for {target_id}")


def ece(y, p, n_bins=10):
    """Expected calibration error with equal-count bins."""
    order = np.argsort(p)
    y, p = np.asarray(y)[order], np.asarray(p)[order]
    bins = np.array_split(np.arange(len(p)), n_bins)
    tot, occ = 0.0, []
    for b in bins:
        if len(b) == 0:
            continue
        occ.append(len(b))
        tot += len(b) / len(p) * abs(y[b].mean() - p[b].mean())
    return float(tot), occ


def log_loss(y, p, eps=1e-6):
    p = np.clip(np.asarray(p, dtype=float), eps, 1 - eps)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def fit_calibrator(kind, x, y):
    if kind == "platt":
        from sklearn.linear_model import LogisticRegression
        m = LogisticRegression(C=1.0, solver="lbfgs")
        m.fit(np.asarray(x).reshape(-1, 1), np.asarray(y))
        return m
    from sklearn.isotonic import IsotonicRegression
    m = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    m.fit(np.asarray(x), np.asarray(y))
    return m


def apply_calibrator(kind, m, x):
    x = np.asarray(x, dtype=float)
    if kind == "platt":
        return m.predict_proba(x.reshape(-1, 1))[:, 1]
    return np.asarray(m.predict(x))


def cv_logloss(kind, x, y, k=5, seed=42):
    x, y = np.asarray(x), np.asarray(y)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(x))
    folds = np.array_split(idx, k)
    losses = []
    for f in folds:
        tr = np.setdiff1d(idx, f)
        if len(np.unique(y[tr])) < 2 or len(f) == 0:
            continue
        m = fit_calibrator(kind, x[tr], y[tr])
        losses.append(log_loss(y[f], apply_calibrator(kind, m, x[f])))
    return float(np.mean(losses)) if losses else float("inf")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="models/qsar_CHEMBL203.pkl")
    ap.add_argument("--n-records", type=int, default=271)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--out", default="eval/calibration.json")
    args = ap.parse_args()

    with open(os.path.join(HERE, args.model), "rb") as fh:
        bundle = pickle.load(fh)
    target = bundle["target_id"]
    seed = bundle["seed"]
    acts, src_file = load_actives(target, args.n_records)

    smiles = [a.get("smiles") or a.get("canonical_smiles") for a in acts]
    y_all = np.asarray([float(a["pchembl_value"]) for a in acts], dtype=np.float32)
    X, fps, keep = featurize(smiles)
    y = y_all[keep]
    smiles = [smiles[i] for i in keep]
    split = scaffold_split(smiles, test_frac=0.2, seed=seed)
    tr, te = split["train_idx"], split["test_idx"]
    perm = np.random.default_rng(seed).permutation(len(tr))
    n_cal = max(10, int(0.2 * len(tr)))
    cal_idx = [tr[i] for i in perm[:n_cal]]
    fit_idx = [tr[i] for i in perm[n_cal:]]
    assert [smiles[i] for i in fit_idx] == list(bundle["train_smiles"]), \
        "reconstructed fit fold does not match the saved model"

    model = bundle["model"]
    model.n_jobs = 1          # joblib's process pool is unavailable in the sandbox
    pred_cal = model.predict(X[cal_idx])
    pred_test = model.predict(X[te])
    y_cal = (y[cal_idx] >= HIT_CUT).astype(int)
    y_test = (y[te] >= HIT_CUT).astype(int)
    print(f"{target}: fit {len(fit_idx)}, calibration {len(cal_idx)} "
          f"(hit rate {y_cal.mean():.3f}), test {len(te)} (hit rate {y_test.mean():.3f})")

    choices = {}
    for kind in ("platt", "isotonic"):
        choices[kind] = cv_logloss(kind, pred_cal, y_cal, seed=seed)
        print(f"  {kind:9s} 5-fold CV log-loss on the calibration fold: {choices[kind]:.4f}")
    selected = min(choices, key=choices.get)
    print(f"  selected: {selected}")
    calib = fit_calibrator(selected, pred_cal, y_cal)

    methods = {
        "uncalibrated_legacy_map": legacy_p_hit(pred_test),
        selected: apply_calibrator(selected, calib, pred_test),
        "base_rate_calibration_fold": np.full(len(te), float(y_cal.mean())),
    }
    report = {}
    for name, p in methods.items():
        e, occ = ece(y_test, p)
        report[name] = {"ece_10bin": round(e, 4), "brier": round(float(np.mean((p - y_test) ** 2)), 4),
                        "log_loss": round(log_loss(y_test, p), 4),
                        "mean_p": round(float(np.mean(p)), 4),
                        "bin_occupancy": occ}
        print(f"  test: {name:28s} ECE {e:.3f}  Brier {report[name]['brier']:.3f}  "
              f"mean p {report[name]['mean_p']:.3f}  (observed {y_test.mean():.3f})")

    passes = report[selected]["ece_10bin"] <= 0.10
    print(f"  pre-registered criterion ECE <= 0.10: {'PASS' if passes else 'FAIL'} "
          f"({report[selected]['ece_10bin']:.3f})")

    # Bootstrap the portfolio probability, propagating calibrator uncertainty.
    rng = np.random.default_rng(seed)
    top = np.argsort(-pred_test)[:8]
    p_ind, p_corr, boot_params = [], [], []
    for _ in range(args.boot):
        b = rng.integers(0, len(cal_idx), len(cal_idx))
        if len(np.unique(y_cal[b])) < 2:
            continue
        m = fit_calibrator(selected, pred_cal[b], y_cal[b])
        if selected == "platt":
            boot_params.append([float(m.coef_[0][0]), float(m.intercept_[0])])
        p = np.clip(apply_calibrator(selected, m, pred_test[top]), 1e-6, 1 - 1e-6)
        p_ind.append(1 - np.prod(1 - p))
        p_corr.append(1 - np.prod(1 - np.array([p.max()])))      # all 8 perfectly correlated
    p_ind, p_corr = np.sort(p_ind), np.sort(p_corr)
    p_point = apply_calibrator(selected, calib, pred_test[top])
    portfolio = {
        "k": int(len(top)),
        "p_hit_per_candidate": [round(float(v), 4) for v in p_point],
        "p_at_least_one_independent": round(float(1 - np.prod(1 - p_point)), 4),
        "p_at_least_one_independent_ci95": [round(float(p_ind[int(0.025 * len(p_ind))]), 4),
                                            round(float(p_ind[int(0.975 * len(p_ind))]), 4)],
        "p_at_least_one_fully_correlated": round(float(p_point.max()), 4),
        "p_at_least_one_fully_correlated_ci95": [round(float(p_corr[int(0.025 * len(p_corr))]), 4),
                                                 round(float(p_corr[int(0.975 * len(p_corr))]), 4)],
        "legacy_uncalibrated_independent": round(float(1 - np.prod(1 - legacy_p_hit(pred_test[top]))), 4),
        "note": "the two rows bracket the correlation assumption: independent candidates versus "
                "one shared chance of success; the truth is in between and is not measured here",
    }
    print(f"  portfolio of {portfolio['k']} best test-fold molecules: "
          f"P(>=1 hit) independent {portfolio['p_at_least_one_independent']} "
          f"{portfolio['p_at_least_one_independent_ci95']}, fully correlated "
          f"{portfolio['p_at_least_one_fully_correlated']} "
          f"{portfolio['p_at_least_one_fully_correlated_ci95']}; "
          f"legacy map gave {portfolio['legacy_uncalibrated_independent']}")

    out = {"target": target, "hit_definition": f"measured pChEMBL >= {HIT_CUT}",
           "source_records": src_file, "n_records": len(smiles),
           "split": {"fit": len(fit_idx), "calibration": len(cal_idx), "test": len(te),
                     "n_scaffolds": split["n_scaffolds"], "method": split["method"]},
           "hit_rate": {"calibration": round(float(y_cal.mean()), 4),
                        "test": round(float(y_test.mean()), 4)},
           "cv_logloss_calibration_fold": {k: round(v, 4) for k, v in choices.items()},
           "selected_calibrator": selected,
           "test_metrics": report,
           "criterion": "ECE <= 0.10 on the held-out test fold (docs/preregistration.md W2)",
           "criterion_met": bool(passes),
           "portfolio": portfolio,
           "bootstrap_resamples": args.boot}
    with open(os.path.join(HERE, args.out), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    with open(os.path.join(HERE, "models", f"hit_calibrator_{target}.pkl"), "wb") as fh:
        pickle.dump({"kind": selected, "model": calib, "hit_cut": HIT_CUT,
                     "boot_params": boot_params,
                     "params": ([float(calib.coef_[0][0]), float(calib.intercept_[0])]
                                if selected == "platt" else None),
                     "fitted_on": "scaffold-split calibration fold", "n_cal": len(cal_idx),
                     "ece_test": report[selected]["ece_10bin"], "target": target,
                     "criterion_met": bool(passes)}, fh)
    # data for the reliability figure
    sel_p = methods[selected]
    with open(os.path.join(HERE, "eval", "figure_data_calibration.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"selected": selected, "y_test": y_test.tolist(),
                   "p_selected": [float(v) for v in sel_p],
                   "p_legacy": [float(v) for v in methods["uncalibrated_legacy_map"]],
                   "pred_test": [float(v) for v in pred_test],
                   "report": report, "portfolio": portfolio}, fh)
    print(f"  wrote {args.out} and models/hit_calibrator_{target}.pkl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
