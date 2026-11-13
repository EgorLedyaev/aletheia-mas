"""Molecule Generator agent -- runs four independent samplers and reports each one's statistics.

The agent never returns a molecule it has not validated with RDKit, never returns a structure
that failed the hazard gate, and always reports per-generator validity / uniqueness / novelty so
a reader can see which sampler actually contributed.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..core.contracts import AgentResult, Candidate
from ..core.context import RunContext
from .base import Agent
from .safety import SafetyAgent

EDIT_SCHEMA = {
    "name": "propose_edits",
    "description": "Propose medicinal-chemistry edits of a seed molecule as SMILES.",
    "input_schema": {
        "type": "object",
        "properties": {
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "smiles": {"type": "string", "description": "Full SMILES of the edited molecule."},
                        "rationale": {"type": "string", "description": "What was changed and why."},
                    },
                    "required": ["smiles", "rationale"],
                },
            }
        },
        "required": ["edits"],
    },
}

EDIT_SYSTEM = (
    "You are a medicinal chemist proposing structural edits. Return complete, valid SMILES for "
    "each edited molecule -- not fragments, not reaction arrows, not names. Keep the core "
    "recognisable: single-point modifications such as substituent changes, bioisosteric "
    "replacements, ring swaps or linker adjustments. Never claim an activity value; the edits "
    "will be scored by independent tools."
)


class MoleculeGeneratorAgent(Agent):
    name = "molecule_generator"
    description = "Four independent generators: rule decoration, BRICS, SELFIES, LLM edits."
    tools = ["generators.rule_decorate", "generators.brics_recombine", "generators.selfies_mutate",
             "generators.validate_proposals", "generators.novelty", "rdkit.validate_batch",
             "hazard.screen_batch"]

    def _llm_edits(self, ctx: RunContext, seed: str, n: int) -> Dict[str, Any]:
        objectives = ctx.blackboard.get("objectives") or []
        obj_txt = ("Optimisation objectives stated by the user: " + "; ".join(objectives)
                   if objectives else "No explicit objective; improve drug-likeness.")
        out = ctx.llm.structured(
            f"Seed molecule (SMILES): {seed}\n{obj_txt}\nPropose {n} distinct single-point edits.",
            EDIT_SCHEMA, system=EDIT_SYSTEM, deterministic=lambda: {"edits": []},
            purpose="generate_edits", max_tokens=1500)
        proposals = (out.get("data") or {}).get("edits") or []
        call = ctx.tools.call("generators.validate_proposals", agent=self.name,
                             proposals=proposals, seed_smiles=seed)
        return {"call": call, "backend": out.get("backend"), "n_proposed": len(proposals)}

    def act(self, ctx: RunContext, step) -> AgentResult:
        t0 = time.time()
        ev: List[Any] = []
        seeds: List[str] = []
        for tok in (step.inputs.get("seeds") or []):
            from rdkit import Chem
            m = Chem.MolFromSmiles(tok)
            if m:
                seeds.append(Chem.MolToSmiles(m))
        for c in ctx.blackboard.get("user_candidates", []):
            seeds.append(c["smiles"])
        actives = ctx.blackboard.get("actives", [])
        if not seeds and actives:
            seeds = [actives[0]["smiles"]]
            ctx.tracer.emit("seed_choice", detail="no user molecule; seeded with the most potent "
                                                 "retrieved active", smiles=seeds[0][:60])
        if not seeds:
            return self.fail(step, "no seed molecule and no retrieved actives to generate from", t0)
        seeds = list(dict.fromkeys(seeds))[:3]
        n_each = int(step.inputs.get("n_per_generator", 40))

        batches: Dict[str, List[Dict[str, Any]]] = {}
        calls: Dict[str, Any] = {}

        single = bool(ctx.cfg.get("ablation", {}).get("single_generator"))
        if single:
            ctx.tracer.emit("ablation", detail="single generator (G1 only)")
        for seed in seeds:
            c1 = ctx.tools.call("generators.rule_decorate", agent=self.name, seed_smiles=seed,
                               n=n_each, seed=ctx.cfg["run"]["seed"])
            if c1.ok:
                batches.setdefault("G1_rule_decorate", []).extend(c1.data["molecules"])
                calls["G1_rule_decorate"] = c1
            c3 = None if single else ctx.tools.call(
                "generators.selfies_mutate", agent=self.name, seed_smiles=seed, n=n_each,
                seed=ctx.cfg["run"]["seed"])
            if c3 is not None and c3.ok:
                batches.setdefault("G3_selfies_mutate", []).extend(c3.data["molecules"])
                calls["G3_selfies_mutate"] = c3
            g4 = None if single else self._llm_edits(ctx, seed, max(6, n_each // 4))
            if g4 is not None and g4["call"].ok:
                batches.setdefault("G4_llm_edits", []).extend(g4["call"].data["molecules"])
                calls["G4_llm_edits"] = g4["call"]
                ev.append(self.ev(ctx, "COMPUTED", "llm_edit_validity",
                                  g4["call"].data["validity"], call=g4["call"], subject=seed,
                                  note=f"{g4['call'].data['n_generated']} of {g4['n_proposed']} "
                                       f"LLM proposals parsed as valid molecules "
                                       f"(backend {g4['backend']})"))
        if actives and not single:
            c2 = ctx.tools.call("generators.brics_recombine", agent=self.name,
                                smiles_list=[a["smiles"] for a in actives[:80]], n=n_each,
                                seed=ctx.cfg["run"]["seed"])
            if c2.ok:
                batches["G2_brics_recombine"] = c2.data["molecules"]
                calls["G2_brics_recombine"] = c2
            else:
                ctx.degrade(f"BRICS recombination failed: {c2.error}")
        elif not single:
            ctx.degrade("BRICS generator skipped: no retrieved actives to fragment")

        if not batches:
            return self.fail(step, "all generators failed", t0)

        # per-generator statistics
        all_mols: List[Dict[str, Any]] = []
        ref = [a["smiles"] for a in actives] if actives else seeds
        gen_stats = {}
        for gname, mols in batches.items():
            smis = [m["smiles"] for m in mols]
            vb = ctx.tools.call("rdkit.validate_batch", agent=self.name, smiles_list=smis)
            nov = ctx.tools.call("generators.novelty", agent=self.name, smiles_list=smis,
                                 reference_smiles=ref, threshold=0.4)
            stats = {"n": len(smis)}
            if vb.ok:
                stats.update({"validity": vb.data["validity"], "uniqueness": vb.data["uniqueness"]})
                ev.append(self.ev(ctx, "COMPUTED", f"{gname}_n_generated", vb.data["n_unique"],
                                  call=vb, note=f"unique valid molecules from {gname}"))
            if nov.ok:
                stats.update({"frac_novel": nov.data["frac_novel"],
                              "mean_max_similarity": nov.data["mean_max_similarity"]})
                ev.append(self.ev(ctx, "COMPUTED", f"{gname}_frac_novel", nov.data["frac_novel"],
                                  call=nov,
                                  note="fraction with max Tanimoto < 0.4 to the retrieved "
                                       "reference set and not an exact duplicate"))
                # registered as a claim so the generator figure can be rebuilt from the run log
                # instead of from a side file that can go stale
                ev.append(self.ev(ctx, "COMPUTED", f"{gname}_mean_max_similarity",
                                  nov.data["mean_max_similarity"], call=nov,
                                  note="mean over candidates of the maximum Tanimoto to the "
                                       "retrieved reference set"))
            gen_stats[gname] = stats
            all_mols.extend(mols)

        # deduplicate across generators
        seen: Dict[str, Dict[str, Any]] = {}
        for m in all_mols:
            if m["smiles"] not in seen:
                seen[m["smiles"]] = m
        unique = list(seen.values())

        # hazard gate on every generated structure
        safety = SafetyAgent()
        scr = safety.screen_structures(ctx, [m["smiles"] for m in unique])
        blocked = set(scr.get("blocked_smiles") or [])
        if scr.get("ok"):
            ev.append(self.ev(ctx, "COMPUTED", "hazard_screened_structures", scr["n_screened"],
                              call=scr["call"],
                              note=f"{scr['n_block']} chemical-weapon-class, {scr['n_review']} "
                                   f"controlled-substance-class, {scr['n_note']} toxicophore flags"))
            if blocked:
                ev.append(self.ev(ctx, "COMPUTED", "hazard_blocked_structures", len(blocked),
                                  call=scr["call"],
                                  note="removed from the candidate set before any scoring"))
        kept = [m for m in unique if m["smiles"] not in blocked]

        cands = [Candidate(cand_id=f"C{i:03d}", smiles=m["smiles"], origin=m["generator"],
                           parent=m.get("parent"), notes=[m.get("transform", "")])
                 for i, m in enumerate(kept, 1)]
        ev.append(self.ev(ctx, "COMPUTED", "candidates_after_dedup_and_safety", len(cands),
                          tool="aletheia.generator", tool_version="1.0",
                          params_hash=f"seeds={len(seeds)},n={n_each}",
                          note=f"{len(all_mols)} raw proposals from {len(batches)} generators -> "
                               f"{len(unique)} unique -> {len(cands)} after the hazard gate"))
        ctx.note("candidates", [c.model_dump() for c in cands])
        ctx.note("generator_stats", gen_stats)
        ctx.note("seeds", seeds)
        return AgentResult(agent=self.name, step_id=step.step_id, evidence=ev,
                           data={"generator_stats": gen_stats, "n_candidates": len(cands),
                                 "n_blocked_by_safety": len(blocked), "seeds": seeds},
                           messages=[f"{len(cands)} candidates from {len(batches)} generators"],
                           duration_s=round(time.time() - t0, 3))
