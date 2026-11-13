"""Property & ADMET agent -- gate 1 of the funnel (cheap, deterministic, runs on everything)."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..core.contracts import AgentResult, Candidate
from ..core.context import RunContext
from ..core.provenance import Applicability, Uncertainty
from .base import Agent

PROFILE_KEYS = ["MolWt", "cLogP", "TPSA", "HBD", "HBA", "RotB", "QED", "SAscore"]


class PropertyAgent(Agent):
    name = "property_agent"
    description = "Descriptors, drug-likeness, structural alerts and ADMET proxies."
    tools = ["rdkit.standardize", "rdkit.descriptors", "rdkit.druglikeness", "rdkit.alerts",
             "admet.profile", "admet.esol_logS", "admet.cns_mpo_like", "admet.liability_alerts"]

    # -- single molecule -----------------------------------------------------
    def profile_one(self, ctx: RunContext, smiles: str, cand_id: str,
                    origin: str = "user", full_admet: bool = True) -> Optional[Candidate]:
        std = ctx.tools.call("rdkit.standardize", agent=self.name, smiles=smiles)
        if not std.ok:
            ctx.degrade(f"invalid structure rejected: {smiles[:40]} ({std.error})")
            return None
        canon = std.data["canonical_smiles"]
        cand = Candidate(cand_id=cand_id, smiles=canon, origin=origin)
        cand.properties["inchikey"] = std.data["inchikey"]
        cand.properties["formula"] = std.data["formula"]
        ik = self.ev(ctx, "COMPUTED", "inchikey", std.data["inchikey"], call=std, subject=canon)
        cand.property_claims["inchikey"] = ik.claim_id

        d = ctx.tools.call("rdkit.descriptors", agent=self.name, smiles=canon)
        if d.ok:
            for k, v in d.data.items():
                if v is None:
                    continue
                cand.properties[k] = v
                e = self.ev(ctx, "COMPUTED", k, v, call=d, subject=canon,
                            units={"MolWt": "Da", "TPSA": "A^2"}.get(k))
                cand.property_claims[k] = e.claim_id
        dl = ctx.tools.call("rdkit.druglikeness", agent=self.name, smiles=canon)
        if dl.ok:
            cand.properties["lipinski_violations"] = dl.data["lipinski_violations"]
            cand.properties["veber_pass"] = dl.data["veber_pass"]
            e = self.ev(ctx, "COMPUTED", "lipinski_violations", dl.data["lipinski_violations"],
                        call=dl, subject=canon, note="Ro5 violations from RDKit descriptors")
            cand.property_claims["lipinski_violations"] = e.claim_id
        al = ctx.tools.call("rdkit.alerts", agent=self.name, smiles=canon)
        if al.ok:
            for catalog, hits in al.data["alerts"].items():
                for h in hits:
                    cand.flags.append(f"{catalog}:{h}")
            cand.properties["n_structural_alerts"] = al.data["n_alerts"]
            e = self.ev(ctx, "COMPUTED", "n_structural_alerts", al.data["n_alerts"], call=al,
                        subject=canon,
                        note=f"catalogs {','.join(al.data['catalogs_used'])} "
                             f"({sum(al.data['catalog_sizes'].values())} patterns)")
            cand.property_claims["n_structural_alerts"] = e.claim_id

        if full_admet:
            ad = ctx.tools.call("admet.profile", agent=self.name, smiles=canon)
            if ad.ok:
                s = ad.data["summary"]
                cand.properties.update({"esol_logS": s["esol_logS"],
                                        "cns_mpo_like": s["cns_mpo_like"],
                                        "n_panels_passed": s["n_panels_passed"],
                                        "herg_risk_flag": s["herg_risk_flag"],
                                        "n_liability_alerts": s["n_liability_alerts"]})
                e1 = self.ev(ctx, "PREDICTED", "esol_logS", s["esol_logS"], call=ad, subject=canon,
                             units="log10(mol/L)", applicability=Applicability.NOT_ASSESSED,
                             note="uncertainty_unavailable: ESOL-type literature equation with "
                                  "unverified constants, no local calibration set")
                e2 = self.ev(ctx, "PREDICTED", "cns_mpo_like", s["cns_mpo_like"], call=ad,
                             subject=canon, applicability=Applicability.NOT_ASSESSED,
                             note="uncertainty_unavailable: CNS-MPO-style desirability sum with "
                                  "unverified breakpoints and a cLogP-1 logD proxy")
                e3 = self.ev(ctx, "COMPUTED", "n_developability_panels_passed",
                             s["n_panels_passed"], call=ad, subject=canon,
                             note="Lipinski/Veber/Egan/Ghose/lead-like/Ro3 panels")
                cand.property_claims["esol_logS"] = e1.claim_id
                cand.property_claims["cns_mpo_like"] = e2.claim_id
                cand.property_claims["n_panels_passed"] = e3.claim_id
                if s["herg_risk_flag"]:
                    cand.flags.append("liability:hERG-type basic amine with cLogP>3")
        return cand

    # -- batch ---------------------------------------------------------------
    def act(self, ctx: RunContext, step) -> AgentResult:
        t0 = time.time()
        ev: List[Any] = []
        if step.action == "profile_candidates":
            cands = [Candidate(**c) for c in ctx.blackboard.get("candidates", [])]
            if not cands:
                return self.fail(step, "no generated candidates to profile", t0)
            profiled = []
            for c in cands:
                p = self.profile_one(ctx, c.smiles, c.cand_id, origin=c.origin,
                                     full_admet=True)
                if p is None:
                    continue
                p.parent = c.parent
                p.notes = list(c.notes)
                p.origin = c.origin
                # Preserve anything an earlier oracle already attached to this candidate.
                p.scores = {**c.scores, **p.scores}
                p.score_claims = {**c.score_claims, **p.score_claims}
                p.properties = {**p.properties, **{k: v for k, v in c.properties.items()
                                                   if k not in p.properties}}
                p.flags = list(dict.fromkeys(list(c.flags) + list(p.flags)))
                profiled.append(p)
            # funnel gate 1: hard structural filters
            gate_cfg = {"max_lipinski_violations": 1, "max_structural_alerts": 1,
                        "max_sa_score": 6.0, "min_qed": 0.30}
            passed, rejected = [], []
            for p in profiled:
                reasons = []
                if p.properties.get("lipinski_violations", 0) > gate_cfg["max_lipinski_violations"]:
                    reasons.append("Ro5 violations")
                if p.properties.get("n_structural_alerts", 0) > gate_cfg["max_structural_alerts"]:
                    reasons.append("structural alerts")
                if (p.properties.get("SAscore") or 0) > gate_cfg["max_sa_score"]:
                    reasons.append("synthetic accessibility")
                if (p.properties.get("QED") or 0) < gate_cfg["min_qed"]:
                    reasons.append("QED below gate")
                if reasons:
                    p.notes.append("gate1 rejected: " + ", ".join(reasons))
                    rejected.append(p)
                else:
                    passed.append(p)
            ev.append(self.ev(ctx, "COMPUTED", "gate1_n_passed", len(passed),
                              tool="aletheia.funnel", tool_version="1.0",
                              params_hash=str(sorted(gate_cfg.items())),
                              note=f"cheap-filter gate over {len(profiled)} candidates: {gate_cfg}"))
            ev.append(self.ev(ctx, "COMPUTED", "gate1_n_rejected", len(rejected),
                              tool="aletheia.funnel", tool_version="1.0",
                              params_hash=str(sorted(gate_cfg.items()))))
            ctx.note("candidates", [c.model_dump() for c in passed])
            ctx.note("candidates_rejected", [c.model_dump() for c in rejected])
            return AgentResult(agent=self.name, step_id=step.step_id, evidence=ev,
                               data={"n_profiled": len(profiled), "n_passed": len(passed),
                                     "n_rejected": len(rejected), "gate": gate_cfg},
                               messages=[f"gate 1: {len(passed)}/{len(profiled)} candidates kept"],
                               duration_s=round(time.time() - t0, 3))

        # default action: profile the molecules named by the user
        tokens = list(step.inputs.get("smiles") or []) or list(ctx.blackboard.get("molecules") or [])
        if not tokens:
            return self.fail(step, "no molecules were provided to profile", t0)
        from .retriever import ChemistryRetrieverAgent
        resolver = ChemistryRetrieverAgent()
        out: List[Candidate] = []
        for i, tok in enumerate(tokens, 1):
            r = resolver.resolve_molecule(ctx, tok)
            if r is None:
                continue
            if r.get("call") is not None and r.get("source_id"):
                ev.append(self.ev(ctx, "RETRIEVED", "structure_source", r["source_id"],
                                  call=r["call"], subject=r["smiles"], source_id=r["source_id"],
                                  source_url=r.get("source_url"),
                                  retrieved_at=r.get("retrieved_at"),
                                  note=f"name {tok!r} resolved via {r['source']}"))
            c = self.profile_one(ctx, r["smiles"], f"U{i}", origin=f"user:{tok}")
            if c:
                c.notes.append(f"input token: {tok}")
                out.append(c)
        if not out:
            return self.fail(step, f"none of {tokens} could be resolved to a valid structure", t0)
        ctx.note("user_candidates", [c.model_dump() for c in out])
        existing = ctx.blackboard.get("candidates", [])
        ctx.note("candidates", existing + [c.model_dump() for c in out])
        return AgentResult(agent=self.name, step_id=step.step_id, evidence=ev,
                           data={"candidates": [c.model_dump() for c in out]},
                           messages=[f"profiled {len(out)} molecule(s)"],
                           duration_s=round(time.time() - t0, 3))
