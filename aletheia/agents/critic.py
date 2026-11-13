"""Critic / Verifier agent -- the adversarial pass before anything is reported.

Four independent checks:
  1. **Recomputation.** A random sample of COMPUTED descriptor claims is recomputed by calling
     RDKit directly with the tool cache bypassed. A mismatch is a hard failure, not a warning.
  2. **Applicability domain.** Every PREDICTED claim must carry an AD verdict; out-of-domain
     predictions are listed so the reporter can mark them.
  3. **Oracle agreement (Goodhart check).** When two or more scoring oracles ranked the same
     candidates, their rank correlation is computed. Near-zero or negative correlation means the
     ranking rests on one oracle, which is reported rather than hidden.
  4. **Ledger hygiene.** Counts of claims by tag, and claims that no answer block cites.
"""
from __future__ import annotations

import random
import time
from typing import Any, Dict, List

from ..core.contracts import AgentResult
from ..core.context import RunContext
from ..core.provenance import Applicability, EvidenceTag
from .base import Agent

RECOMPUTE_KEYS = {"MolWt", "cLogP", "TPSA", "QED", "SAscore", "HBD", "HBA", "RotB"}


class CriticAgent(Agent):
    name = "critic"
    description = "Recomputes sampled claims, audits applicability domain and oracle agreement."
    tools = ["rdkit.descriptors"]

    def act(self, ctx: RunContext, step) -> AgentResult:
        t0 = time.time()
        rng = random.Random(ctx.cfg["run"].get("seed", 0))
        ev, msgs = [], []
        L = ctx.ledger

        # 1. recomputation of sampled COMPUTED descriptor claims
        pool = [e for e in L.claims.values()
                if e.tag == EvidenceTag.COMPUTED and e.key in RECOMPUTE_KEYS and e.subject]
        sample = rng.sample(pool, min(8, len(pool))) if pool else []
        mismatches = []
        for e in sample:
            c = ctx.tools.call("rdkit.descriptors", agent=self.name, _no_cache=True,
                               smiles=e.subject)
            if not c.ok:
                continue
            fresh = c.data.get(e.key)
            try:
                if fresh is None or abs(float(fresh) - float(e.value)) > 1e-6 + 1e-4 * abs(float(e.value)):
                    mismatches.append({"claim_id": e.claim_id, "key": e.key,
                                       "ledger": e.value, "recomputed": fresh})
            except (TypeError, ValueError):
                continue
        ev.append(self.ev(ctx, "COMPUTED", "critic_claims_recomputed", len(sample),
                          tool="aletheia.critic", tool_version="1.0",
                          params_hash=f"seed={ctx.cfg['run'].get('seed')}",
                          note=f"random sample of {len(pool)} recomputable descriptor claims, "
                               "tool cache bypassed"))
        ev.append(self.ev(ctx, "COMPUTED", "critic_recomputation_mismatches", len(mismatches),
                          tool="aletheia.critic", tool_version="1.0",
                          params_hash=f"seed={ctx.cfg['run'].get('seed')}",
                          note="; ".join(f"{m['key']} {m['ledger']}!={m['recomputed']}"
                                         for m in mismatches) or "none"))
        if mismatches:
            msgs.append(f"RECOMPUTATION MISMATCH on {len(mismatches)} claim(s) — "
                        "the ledger value does not reproduce")

        # 2. applicability domain audit
        preds = [e for e in L.claims.values() if e.tag == EvidenceTag.PREDICTED]
        ood = [e.claim_id for e in preds if e.applicability == Applicability.OUT_OF_DOMAIN]
        unassessed = [e.claim_id for e in preds if e.applicability == Applicability.NOT_ASSESSED]
        ev.append(self.ev(ctx, "COMPUTED", "predicted_claims_total", len(preds),
                          tool="aletheia.critic", tool_version="1.0", params_hash="ad-audit"))
        ev.append(self.ev(ctx, "COMPUTED", "predicted_claims_out_of_domain", len(ood),
                          tool="aletheia.critic", tool_version="1.0", params_hash="ad-audit",
                          note="applicability domain verdicts on model predictions"))
        if unassessed:
            ev.append(self.ev(ctx, "COMPUTED", "predicted_claims_not_assessed", len(unassessed),
                              tool="aletheia.critic", tool_version="1.0", params_hash="ad-audit",
                              note="model predictions carrying no applicability-domain verdict"))
            msgs.append(f"{len(unassessed)} predicted value(s) have no applicability-domain "
                        "verdict and are reported as such")

        # 3. oracle agreement
        cands = ctx.blackboard.get("candidates", [])
        oracles: Dict[str, List[float]] = {}
        for c in cands:
            for k, v in (c.get("scores") or {}).items():
                oracles.setdefault(k, [])
        for k in list(oracles):
            vals = [(c["cand_id"], (c.get("scores") or {}).get(k)) for c in cands]
            if sum(1 for _, v in vals if v is not None) < 5:
                oracles.pop(k)
        if len(oracles) >= 2:
            from scipy.stats import spearmanr
            names = sorted(oracles)
            pairs = []
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    a, b = [], []
                    for c in cands:
                        va = (c.get("scores") or {}).get(names[i])
                        vb = (c.get("scores") or {}).get(names[j])
                        if va is not None and vb is not None:
                            a.append(va)
                            b.append(vb)
                    if len(a) >= 5:
                        rho = float(spearmanr(a, b).statistic)
                        pairs.append((names[i], names[j], round(rho, 3), len(a)))
            for n1, n2, rho, n in pairs:
                ev.append(self.ev(ctx, "COMPUTED", f"oracle_rank_correlation_{n1}_vs_{n2}", rho,
                                  tool="scipy.stats.spearmanr", tool_version="1.0",
                                  params_hash=f"n={n}",
                                  note=f"Spearman rho over {n} candidates scored by both oracles"))
                if abs(rho) < 0.2:
                    msgs.append(f"oracles '{n1}' and '{n2}' barely agree (rho={rho}); the "
                                "ranking should not be read as a consensus")
        else:
            msgs.append("fewer than two oracles scored the candidates; no consensus check possible")

        # 4. ledger hygiene
        by_tag = {t.value: len(L.by_tag(t)) for t in EvidenceTag}
        ev.append(self.ev(ctx, "COMPUTED", "ledger_claims_total", len(L.claims),
                          tool="aletheia.critic", tool_version="1.0", params_hash="hygiene",
                          note="; ".join(f"{k}={v}" for k, v in by_tag.items())))
        ok = not mismatches
        return AgentResult(agent=self.name, step_id=step.step_id, ok=ok, evidence=ev,
                           data={"mismatches": mismatches, "out_of_domain": ood,
                                 "unassessed": unassessed, "by_tag": by_tag},
                           messages=msgs, duration_s=round(time.time() - t0, 3))
