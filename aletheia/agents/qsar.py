"""QSAR agent: fits an activity proxy on retrieved actives and scores candidates."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from ..core.contracts import AgentResult
from ..core.context import RunContext
from ..core.provenance import Applicability, Uncertainty
from .base import Agent


class QSARAgent(Agent):
    name = "qsar_agent"
    description = "Scaffold-split activity model with baselines, conformal intervals and AD flags."
    tools = ["qsar.fit", "qsar.predict"]

    def act(self, ctx: RunContext, step) -> AgentResult:
        t0 = time.time()
        actives = ctx.blackboard.get("actives", [])
        target_id = (ctx.blackboard.get("chembl_target") or {}).get("target_chembl_id", "target")
        if len(actives) < 40:
            ctx.degrade(f"QSAR not fitted: only {len(actives)} activity records retrieved "
                        "(minimum 40 for a scaffold split with calibration)")
            return AgentResult(agent=self.name, step_id=step.step_id, ok=False, degraded=True,
                               error=f"insufficient data ({len(actives)} records)",
                               messages=["activity model skipped and reported as skipped"],
                               duration_s=round(time.time() - t0, 3))
        fit = ctx.tools.call("qsar.fit", agent=self.name, actives=actives, target_id=target_id,
                             seed=ctx.cfg["run"]["seed"], test_frac=0.2, alpha=0.1)
        if not fit.ok:
            ctx.degrade(f"QSAR fit failed: {fit.error}")
            return self.fail(step, f"QSAR fit failed: {fit.error}", t0)
        d = fit.data
        mm, b1, b2 = d["metrics_model"], d["metrics_baseline_mean"], d["metrics_baseline_1nn_tanimoto"]
        ev = [
            self.ev(ctx, "COMPUTED", "qsar_test_rmse", mm["rmse"], call=fit, units="pChEMBL",
                    subject=target_id,
                    note=f"scaffold-split test set (n={d['n_test']}); "
                         f"{d['model_type']} on {d['features']}"),
            self.ev(ctx, "COMPUTED", "qsar_test_spearman", mm.get("spearman"), call=fit,
                    subject=target_id, note=f"rank correlation on the held-out scaffolds"),
            self.ev(ctx, "COMPUTED", "qsar_baseline_mean_rmse", b1["rmse"], call=fit,
                    units="pChEMBL", subject=target_id, note="train-mean predictor"),
            self.ev(ctx, "COMPUTED", "qsar_baseline_1nn_rmse", b2["rmse"], call=fit,
                    units="pChEMBL", subject=target_id, note="1-nearest-neighbour Tanimoto predictor"),
            self.ev(ctx, "COMPUTED", "qsar_n_training_records", d["n_fit"], call=fit,
                    subject=target_id,
                    note=f"{d['n_records']} records, {d['split']['n_scaffolds']} scaffolds, "
                         f"{d['n_calibration']} held out for conformal calibration"),
            self.ev(ctx, "COMPUTED", "qsar_conformal_empirical_coverage",
                    d["conformal"]["empirical_test_coverage"], call=fit, subject=target_id,
                    note=f"nominal {d['conformal']['nominal_coverage']}, "
                         f"interval half-width {d['conformal']['q_hat']} pChEMBL"),
        ]
        verdict = ("model beats both baselines" if d["beats_mean_baseline"] and d["beats_1nn_baseline"]
                   else "model beats the mean baseline only" if d["beats_mean_baseline"]
                   else "model does NOT beat the trivial baselines")
        ev.append(self.ev(ctx, "COMPUTED", "qsar_baseline_verdict", verdict, call=fit,
                          subject=target_id,
                          note="RMSE comparison against train-mean and 1-NN predictors"))
        ctx.note("qsar", {"model_path": d["model_path"], "metrics": mm, "verdict": verdict,
                          "conformal": d["conformal"], "test_predictions": d["test_predictions"],
                          "baselines": {"mean": b1, "nn": b2}, "split": d["split"]})

        cands = ctx.blackboard.get("candidates", [])
        n_scored = 0
        if cands and (d["beats_mean_baseline"] or True):
            pr = ctx.tools.call("qsar.predict", agent=self.name, model_path=d["model_path"],
                                smiles_list=[c["smiles"] for c in cands])
            if pr.ok:
                by_smi = {r["smiles"]: r for r in pr.data["predictions"]}
                for c in cands:
                    r = by_smi.get(c["smiles"])
                    if not r:
                        continue
                    e = self.ev(ctx, "PREDICTED", "qsar_pchembl", r["pred_pchembl"], call=pr,
                                units="pChEMBL", subject=c["smiles"],
                                applicability=Applicability(r["applicability"]),
                                uncertainty=Uncertainty(kind="conformal", lower=r["lower"],
                                                        upper=r["upper"], level=1 - pr.data["alpha"],
                                                        note="split-conformal interval"),
                                validation={"test_rmse": mm["rmse"],
                                            "baseline_mean_rmse": b1["rmse"],
                                            "baseline_1nn_rmse": b2["rmse"],
                                            "empirical_coverage": d["conformal"]["empirical_test_coverage"]},
                                note=f"max Tanimoto to training set {r['max_tanimoto_to_train']}")
                    c.setdefault("scores", {})["qsar_pchembl"] = r["pred_pchembl"]
                    c.setdefault("properties", {})["qsar_applicability"] = r["applicability"]
                    c["scores"]["qsar_max_tanimoto_to_train"] = r["max_tanimoto_to_train"]
                    c["scores"]["qsar_lower"] = r["lower"]
                    c["scores"]["qsar_upper"] = r["upper"]
                    c.setdefault("score_claims", {})["qsar_pchembl"] = e.claim_id
                    c.setdefault("properties", {})["qsar_applicability"] = r["applicability"]
                    c["properties"]["qsar_pchembl"] = r["pred_pchembl"]
                    c.setdefault("properties", {})["qsar_applicability"] = r["applicability"]
                    c["scores"]["qsar_max_tanimoto_to_train"] = r["max_tanimoto_to_train"]
                    c["scores"]["qsar_lower"] = r["lower"]
                    c["scores"]["qsar_upper"] = r["upper"]
                    n_scored += 1
                ctx.note("candidates", cands)
                ev.append(self.ev(ctx, "COMPUTED", "qsar_candidates_scored", n_scored, call=pr,
                                  note="candidates with a conformal interval and an AD verdict"))
                n_ood = sum(1 for c in cands
                            if c.get("properties", {}).get("qsar_applicability") == "OUT_OF_DOMAIN")
                ev.append(self.ev(ctx, "COMPUTED", "qsar_candidates_out_of_domain", n_ood, call=pr,
                                  note="predictions outside the model's applicability domain"))
        return AgentResult(agent=self.name, step_id=step.step_id, evidence=ev,
                           data={"metrics": mm, "verdict": verdict, "n_scored": n_scored,
                                 "model_path": d["model_path"], "conformal": d["conformal"]},
                           messages=[f"QSAR on {d['n_records']} records: {verdict}"],
                           duration_s=round(time.time() - t0, 3))
