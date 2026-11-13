"""Does the machinery generalise off EGFR? Re-run the measurable parts on three targets.

Everything in this benchmark is recomputed here from the cached ligand sets: the activity model
is refitted per target with the pipeline's own `qsar_tools.fit` (identical scaffold split, same
hyper-parameters, same conformal calibration), the generators are re-run from a target-appropriate
seed, and the applicability-domain gate is re-applied to their output. Docking enrichment is NOT
recomputed -- it is read from the docking benchmarks that were run with 35 actives and
property-matched measured inactives per target, and the target with no docking benchmark is
reported as not measured rather than interpolated.

    python scripts/make_cross_target_figure.py [--force]

Writes eval/cross_target.json, figures/deck/cross_target_benchmark.png,
docs/cross_target_summary.md.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = 20261111
GEN_COLOUR = {"G1_rule_decorate": "#567183", "G2_brics_recombine": "#a98261",
              "G3_selfies_mutate": "#2b6cb0"}
GEN_SHORT = {"G1_rule_decorate": "G1 rule", "G2_brics_recombine": "G2 BRICS",
             "G3_selfies_mutate": "G3 SELFIES"}


def force_single_thread():
    """Both joblib pools are blocked in this sandbox; one thread gives an identical forest."""
    from sklearn.ensemble._forest import BaseForest
    orig = BaseForest.fit

    def fit(self, X, y, **kw):
        self.n_jobs = 1
        return orig(self, X, y, **kw)

    BaseForest.fit = fit


def chembl_set(target: str, n_expected: int):
    for fp in sorted(glob.glob(os.path.join(HERE, "cache", "tools", "chembl_activities", "*"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                blob = json.load(fh)
        except Exception:
            continue
        data = blob.get("data", blob)
        acts = data.get("activities") if isinstance(data, dict) else None
        if acts and len(acts) == n_expected and acts[0].get("target_chembl_id") == target:
            return [{"smiles": a["smiles"], "pchembl_value": a["pchembl_value"]} for a in acts]
    return []


def thrombin_set():
    p = os.path.join(HERE, "eval", "pubchem_thrombin.json")
    with open(p, encoding="utf-8") as fh:
        blob = json.load(fh)
    recs = [{"smiles": r["smiles"], "pchembl_value": r["pchembl_value"]} for r in blob["records"]
            if r.get("smiles") and r.get("pchembl_value") is not None]
    return recs, blob["rule"]


def docking_auc(target_key):
    """Read the measured ROC AUCs; return {} when that target was never benchmarked."""
    out = {}
    want = {"egfr": ("CHEMBL203", "P00533"), "thrombin": ("CHEMBL204", "P00734"),
            "cdk2": ("CHEMBL301", "P24941")}.get(target_key.lower(), ())
    for fp in sorted(glob.glob(os.path.join(HERE, "eval", "docking_benchmark_*.json"))):
        with open(fp, encoding="utf-8") as fh:
            blob = json.load(fh)
        for rec in blob.get("receptors", []):
            if rec.get("target") not in want and rec.get("accession") not in want:
                continue
            for sf, res in (rec.get("scoring") or {}).items():
                out[f"{rec['pdb']} / {sf}"] = {
                    "auc": res["roc_auc"], "lo": res["auc_ci95"][0], "hi": res["auc_ci95"][1],
                    "n_active": rec.get("n_actives"), "n_decoy": rec.get("n_decoys"),
                    "usable": res.get("usable_for_ranking")}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="refit even if eval/cross_target.json exists")
    args = ap.parse_args(argv)
    sys.path.insert(0, HERE)
    cache_path = os.path.join(HERE, "eval", "cross_target.json")

    if args.force or not os.path.exists(cache_path):
        import aletheia.tools.generators as G
        import aletheia.tools.qsar_tools as Q
        force_single_thread()

        egfr = chembl_set("CHEMBL203", 271)
        cdk2 = chembl_set("CHEMBL301", 267)
        thr, thr_rule = thrombin_set()
        targets = [
            {"key": "EGFR", "label": "EGFR (CHEMBL203)", "uniprot": "P00533",
             "source": "ChEMBL activities, cached tool call", "records": egfr,
             "note": "the target the whole pipeline was developed on"},
            {"key": "CDK2", "label": "CDK2 (CHEMBL301)", "uniprot": "P24941",
             "source": "ChEMBL activities, cached tool call", "records": cdk2,
             "note": "a second kinase, never used during development"},
            {"key": "thrombin", "label": "thrombin (P00734)", "uniprot": "P00734",
             "source": "PubChem BioAssay dose-response, " + thr_rule, "records": thr,
             "note": "a serine protease: different fold, different chemotype"},
        ]
        results = []
        for t in targets:
            recs = t["records"]
            if len(recs) < 40:
                results.append({**{k: v for k, v in t.items() if k != "records"},
                                "n_records": len(recs), "qsar": None})
                continue
            fit = Q.fit(recs, target_id=f"xt_{t['key']}", seed=SEED,
                        model_dir=os.path.join(HERE, "models", "cross_target"))
            seed_smiles = max(recs, key=lambda r: float(r["pchembl_value"]))["smiles"]
            gens = {}
            all_gen = []
            for name, fn, kw in (("G1_rule_decorate", G.rule_decorate, {"seed_smiles": seed_smiles}),
                                 ("G3_selfies_mutate", G.selfies_mutate, {"seed_smiles": seed_smiles}),
                                 ("G2_brics_recombine", G.brics_recombine,
                                  {"smiles_list": [r["smiles"] for r in recs[:60]]})):
                try:
                    out = fn(n=40, seed=SEED, **kw)
                    mols = [m["smiles"] if isinstance(m, dict) else m for m in out["molecules"]]
                    nov = G.novelty(mols, [r["smiles"] for r in recs], threshold=0.4)
                    gens[name] = {"requested": 40, "delivered": int(out["n_generated"]),
                                  "yield": round(out["n_generated"] / 40.0, 4),
                                  "novel_fraction": nov.get("novel_fraction",
                                                            nov.get("fraction_novel"))}
                    all_gen += mols
                except Exception as exc:                                   # noqa: BLE001
                    gens[name] = {"requested": 40, "delivered": 0, "yield": 0.0,
                                  "error": f"{type(exc).__name__}: {exc}"}
            ad = None
            if all_gen:
                pred = Q.predict(fit["model_path"], all_gen)
                flags = [str(p.get("applicability", "")).lower()
                         for p in pred["predictions"]]
                ad = {"n": len(flags),
                      "in_domain": round(sum(f == "in_domain" for f in flags) / len(flags), 4),
                      "borderline": round(sum(f == "borderline" for f in flags) / len(flags), 4),
                      "out_of_domain": round(sum(f == "out_of_domain" for f in flags) / len(flags), 4)}
            results.append({**{k: v for k, v in t.items() if k != "records"},
                            "n_records": len(recs), "seed_smiles": seed_smiles,
                            "qsar": {"rmse_model": fit["metrics_model"]["rmse"],
                                     "r2_model": fit["metrics_model"].get("r2"),
                                     "rmse_1nn": fit["metrics_baseline_1nn_tanimoto"]["rmse"],
                                     "rmse_mean": fit["metrics_baseline_mean"]["rmse"],
                                     "n_fit": fit["n_fit"], "n_test": fit["n_test"],
                                     "y_std": fit["y_std"],
                                     "beats_1nn": fit["beats_1nn_baseline"],
                                     "beats_mean": fit["beats_mean_baseline"]},
                            "conformal": fit["conformal"], "generators": gens,
                            "applicability": ad,
                            "docking": docking_auc(t["key"].lower())})
        blob = {"seed": SEED, "protocol": "qsar_tools.fit, scaffold split test_frac 0.2, "
                                          "RF 300 trees, split-conformal alpha 0.1",
                "targets": results}
        with open(cache_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(blob, fh, indent=1)
    with open(cache_path, encoding="utf-8") as fh:
        blob = json.load(fh)
    render(blob)
    write_summary(blob)
    for t in blob["targets"]:
        q = t["qsar"]
        print(f"{t['key']:9s} n={t['n_records']:4d} rmse {q['rmse_model']:.3f} "
              f"(1nn {q['rmse_1nn']:.3f}, mean {q['rmse_mean']:.3f}) "
              f"coverage {t['conformal']['empirical_test_coverage']:.3f} "
              f"docking pairs {len(t['docking'])}")
    return 0


def render(blob):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    matplotlib.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 200, "font.size": 9, "axes.titlesize": 10,
        "axes.labelsize": 8.6, "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 7.6,
        "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#444444",
        "axes.linewidth": 0.8, "text.color": "#141821", "figure.facecolor": "white"})
    ts = blob["targets"]
    names = [t["key"] for t in ts]
    x = np.arange(len(ts))
    fig, axes = plt.subplots(2, 3, figsize=(13.2, 7.4))

    ax = axes[0][0]
    w = 0.26
    for i, (key, lab, col) in enumerate((("rmse_model", "our model", "#2b6cb0"),
                                         ("rmse_1nn", "1-NN Tanimoto", "#9aa4b2"),
                                         ("rmse_mean", "train mean", "#c9ced6"))):
        vals = [t["qsar"][key] for t in ts]
        ax.bar(x + (i - 1) * w, vals, w, color=col, label=lab, edgecolor="white", linewidth=0.6)
        for xx, v in zip(x + (i - 1) * w, vals):
            ax.text(xx, v + 0.02, f"{v:.2f}", ha="center", va="bottom", fontsize=6.8)
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylabel("test RMSE (log units, lower is better)")
    ax.set_title("activity model vs its own baselines")
    ax.legend(frameon=False, loc="upper left")
    ax.set_ylim(0, max(t["qsar"]["rmse_mean"] for t in ts) * 1.28)

    ax = axes[0][1]
    cov = [t["conformal"]["empirical_test_coverage"] for t in ts]
    wid = [t["conformal"]["interval_width"] for t in ts]
    bars = ax.bar(x, cov, 0.5, color=["#2f7d52" if c >= 0.9 else "#b4443c" for c in cov],
                  edgecolor="white")
    ax.axhline(ts[0]["conformal"]["nominal_coverage"], color="#141821", linestyle="--",
               linewidth=1.0)
    ax.text(-0.42, ts[0]["conformal"]["nominal_coverage"] + 0.015, "nominal 90%",
            ha="left", fontsize=7.4)
    for b, c, wd in zip(bars, cov, wid):
        ax.text(b.get_x() + b.get_width() / 2, c + 0.025, f"{c:.3f}\ninterval ±{wd / 2:.2f} log",
                ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylim(0, 1.18)
    ax.set_ylabel("empirical coverage on the test scaffolds")
    ax.set_title("conformal interval keeps its promise")

    ax = axes[0][2]
    labels, vals, los, his = [], [], [], []
    for t in ts:
        for k, d in sorted(t["docking"].items()):
            labels.append(f"{t['key']}\n{k}")
            vals.append(d["auc"])
            los.append(d["auc"] - d["lo"])
            his.append(d["hi"] - d["auc"])
    if vals:
        y = np.arange(len(vals))
        cols = ["#2f7d52" if lo > 0.5 else ("#b4443c" if v + h < 0.5 else "#9aa4b2")
                for v, lo, h in zip(vals, [v - l for v, l in zip(vals, los)], his)]
        cols = ["#2f7d52" if (v - l) > 0.5 else ("#b4443c" if (v + h) < 0.5 else "#9aa4b2")
                for v, l, h in zip(vals, los, his)]
        ax.errorbar(vals, y, xerr=[los, his], fmt="none", ecolor="#5d6675", elinewidth=1.1,
                    capsize=2.5, zorder=1)
        ax.scatter(vals, y, s=42, c=cols, zorder=2, edgecolor="white", linewidth=0.7)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=7)
        ax.axvline(0.5, color="#141821", linestyle="--", linewidth=1.0)
        ax.set_xlim(0.0, 1.0)
        ax.set_xlabel("ROC AUC, actives vs measured inactives (95% CI)")
    missing = [t["key"] for t in ts if not t["docking"]]
    ax.set_title("docking enrichment, where it was benchmarked")
    if missing:
        ax.text(0.02, -0.33, "not benchmarked: " + ", ".join(missing), transform=ax.transAxes,
                fontsize=7.4, color="#b4443c")

    ax = axes[1][0]
    gens = list(GEN_SHORT)
    w = 0.26
    for i, g in enumerate(gens):
        vals = [t["generators"].get(g, {}).get("yield", 0.0) for t in ts]
        ax.bar(x + (i - 1) * w, vals, w, color=GEN_COLOUR[g], label=GEN_SHORT[g],
               edgecolor="white", linewidth=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylim(0, 1.25)
    ax.set_ylabel("delivered / 40 requested")
    ax.set_title("generators run on each target's own chemotype")
    ax.legend(frameon=False, ncol=3, loc="upper center", fontsize=7)

    ax = axes[1][1]
    bottom = np.zeros(len(ts))
    for key, lab, col in (("in_domain", "in domain", "#2f7d52"),
                          ("borderline", "borderline", "#d9a441"),
                          ("out_of_domain", "out of domain", "#b4443c")):
        vals = np.array([(t["applicability"] or {}).get(key, 0.0) for t in ts])
        ax.bar(x, vals, 0.5, bottom=bottom, color=col, label=lab, edgecolor="white", linewidth=0.6)
        bottom += vals
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("fraction of generated molecules")
    ax.set_title("applicability-domain gate on fresh output")
    ax.legend(frameon=False, ncol=3, fontsize=7, loc="lower center")

    ax = axes[1][2]
    ax.axis("off")
    ax.set_title("what the system does with that evidence")
    lines = []
    for t in ts:
        ok = [k for k, d in t["docking"].items() if d["lo"] > 0.5]
        if not t["docking"]:
            verdict = "docking never admitted — no benchmark on this receptor"
        elif ok:
            verdict = "docking admitted on " + ", ".join(ok)
        else:
            verdict = "docking score dropped from the objective — no pair beats chance"
        q = t["qsar"]
        lines.append(f"{t['key']} — model beats 1-NN: {'yes' if q['beats_1nn'] else 'no'}; "
                     f"beats train mean: {'yes' if q['beats_mean'] else 'no'}\n{verdict}\n"
                     f"P(>=1 hit) withheld (calibrator exists for EGFR only)")
    ax.text(0.0, 0.96, "\n\n".join(lines), transform=ax.transAxes, va="top", fontsize=7.8,
            linespacing=1.5, wrap=True)

    fig.suptitle("Does it generalise? The same protocol re-run on three targets",
                 fontsize=12.5, y=0.985)
    note = (f"Activity models refitted here with aletheia.tools.qsar_tools.fit (seed {blob['seed']}, "
            "scaffold split, RF 300 trees, split-conformal alpha 0.1) on the cached ligand sets; "
            "generators re-run from each target's most potent record. Docking AUCs are read from "
            "eval/docking_benchmark_*.json (35 actives vs property-matched measured inactives) and "
            "are not recomputed. The thrombin set comes from PubChem dose-response assays and has "
            "no records between pAct 5 and 7 by construction, so its RMSE is comparable to its own "
            "baselines, not to the ChEMBL targets.")
    import textwrap
    fig.text(0.012, 0.012, "\n".join(textwrap.wrap(note, 165)), fontsize=6.9, color="#5d6675",
             va="bottom", linespacing=1.5)
    fig.tight_layout(rect=(0, 0.085, 1, 0.955))
    out = os.path.join(HERE, "figures", "deck", "cross_target_benchmark.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, facecolor="white")
    plt.close(fig)


def write_summary(blob):
    ts = blob["targets"]
    L = ["# Cross-target generalisation — EGFR, CDK2, thrombin", "",
         "Generated by `scripts/make_cross_target_figure.py`; figure: "
         "`figures/deck/cross_target_benchmark.png`; raw numbers: `eval/cross_target.json`.", "",
         "The question this answers is the one a jury asks after a single-target demo: *is the "
         "machinery tuned to EGFR, or does it behave the same way on a target it has never seen?* "
         "Every number below was recomputed by this script with the pipeline's own functions, "
         "except the docking AUCs, which are read from the docking benchmarks.", "",
         "| Target | Ligand records | Source | Test RMSE | 1-NN | train mean | Conformal coverage "
         "(nominal 0.90) | Docking pairs benchmarked |", "|---|---|---|---|---|---|---|---|"]
    for t in ts:
        q, c = t["qsar"], t["conformal"]
        L.append(f"| {t['label']} | {t['n_records']} | {t['source'].split(',')[0]} | "
                 f"**{q['rmse_model']:.3f}** | {q['rmse_1nn']:.3f} | {q['rmse_mean']:.3f} | "
                 f"{c['empirical_test_coverage']:.3f} | {len(t['docking'])} |")
    L += ["", "## What moved and what did not", ""]
    for t in ts:
        q = t["qsar"]
        ok = [k for k, d in t["docking"].items() if d["lo"] > 0.5]
        bad = [k for k, d in t["docking"].items() if d["hi"] < 0.5]
        L.append(f"**{t['label']}** — {t['note']}. The refitted model "
                 f"{'beats' if q['beats_1nn'] else 'does not beat'} the 1-NN baseline and "
                 f"{'beats' if q['beats_mean'] else 'does not beat'} the train mean "
                 f"(y std {q['y_std']}), on {q['n_test']} held-out scaffolds.")
        if t["docking"]:
            parts = []
            for k, d in sorted(t["docking"].items()):
                parts.append(f"{k}: AUC {d['auc']:.3f} [{d['lo']:.3f}, {d['hi']:.3f}]")
            L.append("Docking enrichment — " + "; ".join(parts) + ". " +
                     (f"Admitted into the ranking objective: {', '.join(ok)}." if ok else
                      "No pair has a lower bound above chance, so the docking score is dropped "
                      "from the ranking objective for this target.") +
                     (f" Ordering is inverted on {', '.join(bad)} — decoys score better than "
                      "actives." if bad else ""))
        else:
            L.append("No docking benchmark was run on this target, so no docking score is "
                     "admitted into the ranking objective; the ranker degrades to the "
                     "property-and-model objective and says so in the answer.")
        g = t["generators"]
        L.append("Generator yield from this target's most potent record: " +
                 ", ".join(f"{GEN_SHORT[k]} {v['delivered']}/40" for k, v in g.items()
                           if k in GEN_SHORT) + ".")
        a = t["applicability"] or {}
        if a:
            L.append(f"Applicability-domain gate on that output: {a['in_domain']:.2f} in domain, "
                     f"{a['borderline']:.2f} borderline, {a['out_of_domain']:.2f} out of domain — "
                     "out-of-domain molecules get no activity number in the answer.")
        L.append("")
    L += ["## Honest limits of this benchmark", "",
          "- BRAF and BAX were requested as the third target. The ChEMBL web API returned HTTP 500 "
          "on every endpoint for the whole of this work, and no BRAF or BAX ligand set is in the "
          "local tool cache, so neither could be fitted. CDK2 (CHEMBL301) and thrombin (P00734) "
          "are the two targets for which measured ligand sets were already on disk; thrombin is "
          "the more informative of the two because it is not a kinase.",
          "- The thrombin set is a two-mode selection (PubChem dose-response actives at pAct >= 7 "
          "and measured inactives at pAct <= 5, nothing between), so its absolute RMSE is not "
          "comparable with the ChEMBL sets. Its baselines are computed on the same split, which is "
          "what the comparison rests on.",
          "- Docking was benchmarked only on EGFR and thrombin receptors. CDK2 has no receptor "
          "validation here, and the system's response to that is to refuse the docking score, not "
          "to use it unvalidated.",
          "- A hit-probability calibrator exists for EGFR only. `P(>=1 hit)` is withheld on all "
          "three targets in published answers (see `docs/evaluation_report.md`, W2).",
          "- Generator yield is *delivered / requested*, not a validity rate: the generators "
          "already discard unparseable structures internally, so a low yield means the generator "
          "could not find 40 distinct valid edits on that chemotype, which is the thing worth "
          "knowing.", ""]
    path = os.path.join(HERE, "docs", "cross_target_summary.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
