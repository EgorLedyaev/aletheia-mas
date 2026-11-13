"""Ranker / Portfolio agent: Pareto ranking, diversity clustering, portfolio selection."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from ..core.contracts import AgentResult
from ..core.context import RunContext
from ..core.provenance import Applicability, Uncertainty
from .base import Agent

OBJECTIVES = {"qsar_pchembl": "max", "vina_score": "min", "QED": "max", "SAscore": "min",
              "n_structural_alerts": "min"}


class RankerAgent(Agent):
    name = "ranker"
    description = "Multi-objective Pareto ranking with diversity-aware portfolio selection."
    tools = ["ranking.pareto_front", "ranking.butina_clusters", "ranking.portfolio"]

    def act(self, ctx: RunContext, step) -> AgentResult:
        t0 = time.time()
        cands = ctx.blackboard.get("candidates", [])
        if not cands:
            return self.fail(step, "no candidates to rank", t0)
        # A docking score may only act as a ranking objective where its enrichment was measured
        # and passed (docs/preregistration.md W3). On receptors where it failed -- or where the
        # ordering is inverted, as on thrombin -- it is still reported, but it does not rank.
        objectives = dict(OBJECTIVES)
        docking_validated = ctx.blackboard.get("docking_oracle_validated")
        if docking_validated is False and "vina_score" in objectives:
            objectives.pop("vina_score")
            ctx.degrade("vina_score excluded from the ranking objectives: its enrichment on this "
                        "receptor does not pass the pre-registered criterion; it is reported but "
                        "does not order candidates")
        rows = []
        for c in cands:
            r = {"cand_id": c["cand_id"]}
            for k in objectives:
                r[k] = (c.get("scores") or {}).get(k, (c.get("properties") or {}).get(k))
            rows.append(r)
        ev: List[Any] = []
        pf = ctx.tools.call("ranking.pareto_front", agent=self.name, rows=rows,
                            objectives=objectives)
        front_of: Dict[str, int] = {}
        if pf.ok and pf.data["fronts"]:
            front_of = pf.data["front_of"]
            ev.append(self.ev(ctx, "COMPUTED", "pareto_front_size", len(pf.data["fronts"][0]),
                              call=pf, note=f"objectives: {', '.join(pf.data['objectives_used'])}; "
                                            f"{pf.data['n_fronts']} fronts over "
                                            f"{pf.data['n_usable']} fully-scored candidates"))
        else:
            ctx.degrade("Pareto ranking skipped: not enough candidates with all objectives scored")

        cl = ctx.tools.call("ranking.butina_clusters", agent=self.name,
                            smiles_list=[c["smiles"] for c in cands], cutoff=0.35)
        if cl.ok:
            ev.append(self.ev(ctx, "COMPUTED", "n_chemotype_clusters", cl.data["n_clusters"],
                              call=cl, note=cl.data["method"]))

        score_key = "qsar_pchembl" if any((c.get("scores") or {}).get("qsar_pchembl") is not None
                                          for c in cands) else "vina_score"
        target_id = (ctx.blackboard.get("target_chembl_id")
                     or (ctx.blackboard.get("target") or {}).get("target_chembl_id"))
        pt = ctx.tools.call("ranking.portfolio", agent=self.name, candidates=cands,
                            k=int(step.inputs.get("k", 8)), cutoff=0.35, score_key=score_key,
                            target_id=target_id)
        selected_ids: List[str] = []
        if pt.ok:
            selected_ids = [s["cand_id"] for s in pt.data["selected"]]
            ev.append(self.ev(ctx, "COMPUTED", "portfolio_size", len(selected_ids), call=pt,
                              note=f"{pt.data['n_clusters_represented']} chemotype clusters "
                                   f"represented, scored on {score_key}"))
            cal = pt.data.get("calibration") or {}
            ad = (Applicability.IN_DOMAIN if cal.get("criterion_met")
                  else Applicability.NOT_ASSESSED)
            ci_i = pt.data.get("p_at_least_one_hit_independent_ci95")
            ci_c = pt.data.get("p_at_least_one_hit_cluster_correlated_ci95")
            ci_f = pt.data.get("p_at_least_one_hit_fully_correlated_ci95")
            rho = pt.data.get("oracle_disagreement_spearman")
            base = f"{pt.data['probability_model']}. {pt.data['caveat']}"
            if pt.data.get("n_without_probability_out_of_domain"):
                base += (f" {pt.data['n_without_probability_out_of_domain']} selected candidates "
                         f"are outside the model's applicability domain and carry no probability.")

            def unc(ci):
                if not ci:
                    return None
                return Uncertainty(kind="interval", lower=ci[0], upper=ci[1], level=0.95,
                                   note="2000-resample bootstrap refit of the hit calibrator on "
                                        "the scaffold-split calibration fold")

            for key, val, ci, extra in (
                    ("p_at_least_one_hit_independent",
                     pt.data["p_at_least_one_hit_independent"], ci_i, ""),
                    ("p_at_least_one_hit_cluster_correlated",
                     pt.data["p_at_least_one_hit_cluster_correlated"], ci_c,
                     "assumes candidates within a chemotype cluster fail together; "
                     "the lower of the two bounds. "),
                    ("p_at_least_one_hit_fully_correlated",
                     pt.data.get("p_at_least_one_hit_fully_correlated"), ci_f,
                     "most conservative bound: all selected candidates treated as one shared "
                     "chance of success. ")):
                if val is None:
                    continue
                note = extra + base
                kwargs = {"applicability": ad, "note": note}
                u = unc(ci)
                if u is not None:
                    kwargs["uncertainty"] = u
                else:
                    kwargs["note"] = "uncertainty_unavailable: " + note
                ev.append(self.ev(ctx, "PREDICTED", key, val, call=pt, **kwargs))
            if rho is not None:
                ev.append(self.ev(ctx, "COMPUTED", "oracle_disagreement_spearman", rho, call=pt,
                                  note="Spearman rho between the activity model and docking over "
                                       "candidates scored by both; printed next to every "
                                       "portfolio probability"))

        withheld_keys: List[str] = []
        if pt.ok and not ((pt.data.get("calibration") or {}).get("criterion_met")):
            withheld_keys = ["p_at_least_one_hit_independent",
                             "p_at_least_one_hit_cluster_correlated",
                             "p_at_least_one_hit_fully_correlated"]

        # composite ordering: Pareto front first, then the portfolio score key
        def sort_key(c):
            fr = front_of.get(c["cand_id"], 99)
            s = (c.get("scores") or {}).get(score_key)
            s = (-s if score_key == "qsar_pchembl" else s) if s is not None else 999
            return (fr, s, -(c.get("properties", {}).get("QED") or 0))

        ordered = sorted(cands, key=sort_key)
        for i, c in enumerate(ordered, 1):
            c["rank"] = i
            c["selected"] = c["cand_id"] in selected_ids
        ctx.note("candidates", ordered)
        ctx.note("portfolio", pt.data if pt.ok else None)
        ctx.note("pareto", pf.data if pf.ok else None)
        return AgentResult(agent=self.name, step_id=step.step_id, evidence=ev,
                           data={"n_ranked": len(ordered), "selected": selected_ids,
                                 "score_key": score_key,
                                 "withheld_keys": withheld_keys,
                                 "portfolio": pt.data if pt.ok else None},
                           messages=[f"ranked {len(ordered)} candidates; "
                                     f"portfolio of {len(selected_ids)} selected"],
                           duration_s=round(time.time() - t0, 3))
