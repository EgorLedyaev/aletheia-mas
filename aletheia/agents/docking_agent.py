"""Docking & Interaction agent.

Every docking campaign in Aletheia carries its own validation: before any candidate is scored,
the co-crystal ligand of the selected structure is re-docked into the same prepared receptor and
the RMSD to the crystallographic pose is reported. A campaign whose redocking RMSD is above the
2 A convention is still reported -- with the warning attached to each score.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from ..core.contracts import AgentResult
from ..core.context import RunContext
from .base import Agent


class DockingAgent(Agent):
    name = "docking_agent"
    description = "Vina docking with redocking validation and geometric interaction analysis."
    tools = ["docking.vina_version", "docking.prepare_receptor", "docking.prepare_ligand",
             "docking.box_from_ligand_pdb", "docking.vina_dock", "docking.pose_rmsd",
             "docking.contacts", "docking.pose_to_sdf", "pdb.extract_receptor",
             "pdb.extract_ligand", "pdb.chemcomp"]

    @staticmethod
    @staticmethod
    def _receptor_enrichment(pdb_id: str, scoring: str = "vina",
                             path: str = "eval/docking_benchmark.json",
                             legacy: str = "eval/docking_validation.json"
                             ) -> Optional[Dict[str, Any]]:
        """Measured enrichment for THIS receptor and THIS scoring function, if it has been run.

        A docking score is only as informative as the setup's measured ability to separate known
        actives from measured inactives on the same receptor with the same scoring function, so
        that measurement travels with every score this agent emits -- including when it is
        unflattering, and including when it says the ordering is inverted.

        `usable_for_ranking` is the pre-registered rule (docs/preregistration.md W3): the lower
        bound of the ROC AUC 95% interval must exceed 0.5.
        """
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, json.JSONDecodeError):
                d = None
            if d:
                for rec in d.get("receptors", []):
                    if str(rec.get("pdb", "")).upper() != str(pdb_id).upper():
                        continue
                    sc = (rec.get("scoring") or {}).get(scoring)
                    if not sc:
                        continue
                    return {"roc_auc": sc.get("roc_auc"), "auc_ci95": sc.get("auc_ci95"),
                            "ef_10pct": sc.get("ef_10pct"), "score_gap": sc.get("score_gap"),
                            "n_actives": rec.get("n_actives"), "n_decoys": rec.get("n_decoys"),
                            "decoy_class": rec.get("decoy_class"),
                            "scoring_function": scoring,
                            "usable_for_ranking": bool(sc.get("usable_for_ranking")),
                            "ordering_inverted": bool((sc.get("score_gap") or 0) > 0),
                            "discriminates": bool(sc.get("usable_for_ranking")),
                            "source": "eval/docking_benchmark.json "
                                      "(scripts/bench_docking.py, measured inactives)"}
        if not os.path.exists(legacy):
            return None
        try:
            with open(legacy, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None
        if str(d.get("pdb_id", "")).upper() != str(pdb_id).upper():
            return None
        return {"roc_auc": d.get("roc_auc"), "ef_10pct": d.get("ef_10pct"),
                "n_actives": d.get("n_actives"), "n_decoys": d.get("n_decoys"),
                "mean_score_actives": d.get("mean_score_actives"),
                "mean_score_decoys": d.get("mean_score_decoys"),
                "discriminates": bool((d.get("roc_auc") or 0) >= 0.7),
                "usable_for_ranking": bool((d.get("roc_auc") or 0) >= 0.7),
                "limitation": d.get("limitation")}

    def _receptor(self, ctx: RunContext) -> Optional[Dict[str, Any]]:
        pdb_path = ctx.blackboard.get("receptor_pdb_path")
        pdb_id = ctx.blackboard.get("pdb_id") or "model"
        if not pdb_path:
            ctx.degrade("docking skipped: no receptor structure was resolved")
            return None
        chain = ctx.blackboard.get("receptor_chain")
        rec_pdb = f"cache/docking/{pdb_id}_rec.pdb"
        ex = ctx.tools.call("pdb.extract_receptor", agent=self.name, pdb_path=pdb_path,
                            out_path=rec_pdb, chain=chain)
        if not ex.ok:
            ctx.degrade(f"receptor extraction failed: {ex.error}")
            return None
        pr = ctx.tools.call("docking.prepare_receptor", agent=self.name, pdb_path=rec_pdb,
                            out_pdbqt=f"cache/docking/{pdb_id}_rec.pdbqt")
        if not pr.ok:
            ctx.degrade(f"receptor preparation failed: {pr.error}")
            return None
        return {"pdb_id": pdb_id, "rec_pdb": rec_pdb, "rec_pdbqt": pr.data["path"],
                "n_atoms": pr.data["n_atoms"], "call": pr, "chain": chain}

    def _box(self, ctx: RunContext, rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        coc = ctx.blackboard.get("cocrystal")
        pdb_path = ctx.blackboard.get("receptor_pdb_path")
        if coc:
            lig_pdb = f"cache/docking/{rec['pdb_id']}_{coc['resname']}.pdb"
            ex = ctx.tools.call("pdb.extract_ligand", agent=self.name, pdb_path=pdb_path,
                                resname=coc["resname"], out_path=lig_pdb, chain=coc["chain"])
            if ex.ok:
                bx = ctx.tools.call("docking.box_from_ligand_pdb", agent=self.name,
                                    ligand_pdb=lig_pdb, pad=float(ctx.cfg["docking"]["box_pad"]))
                if bx.ok:
                    return {"center": bx.data["center"], "size": bx.data["size"],
                            "origin": f"co-crystal ligand {coc['resname']}", "ligand_pdb": lig_pdb,
                            "resname": coc["resname"], "call": bx}
        pockets = ctx.blackboard.get("pockets") or []
        if pockets:
            p = pockets[0]
            size = [max(18.0, round(e + 6, 1)) for e in p["extent_A"]]
            return {"center": p["center"], "size": size,
                    "origin": "LIGSITE-style detected pocket (rank 1)", "ligand_pdb": None,
                    "resname": None, "call": None}
        ctx.degrade("docking skipped: no binding site could be defined "
                    "(no co-crystal ligand and no detected pocket)")
        return None

    def act(self, ctx: RunContext, step) -> AgentResult:
        t0 = time.time()
        ev: List[Any] = []
        rec = self._receptor(ctx)
        if rec is None:
            return self.fail(step, "no usable receptor", t0)
        box = self._box(ctx, rec)
        if box is None:
            return self.fail(step, "no binding site definition", t0)

        vv = ctx.tools.call("docking.vina_version", agent=self.name)
        # Which scoring function: the step may name one (S05 uses the pair that passes its
        # enrichment criterion on this receptor, S05b deliberately uses the one that does not).
        scoring = str(step.inputs.get("scoring") or ctx.cfg["docking"].get("scoring") or "vina")
        exh = int(ctx.cfg["docking"]["exhaustiveness"])
        seed = int(ctx.cfg["docking"]["seed"])
        n_modes = int(ctx.cfg["docking"]["num_modes"])

        # -- validation: redock the co-crystal ligand -------------------------
        validation: Dict[str, Any] = {"performed": False}
        if box.get("resname"):
            cc = ctx.tools.call("pdb.chemcomp", agent=self.name, comp_id=box["resname"])
            if cc.ok and cc.data.get("smiles"):
                lp = ctx.tools.call("docking.prepare_ligand", agent=self.name,
                                    smiles=cc.data["smiles"],
                                    out_pdbqt=f"cache/docking/redock_{box['resname']}.pdbqt",
                                    seed=seed)
                if lp.ok:
                    redock_exh = int(ctx.cfg["docking"].get("redock_exhaustiveness", exh))
                    rd = ctx.tools.call("docking.vina_dock", scoring=scoring, agent=self.name,
                                        receptor_pdbqt=rec["rec_pdbqt"], ligand_pdbqt=lp.data["path"],
                                        center=box["center"], size=box["size"],
                                        out_pdbqt=f"cache/docking/redock_{box['resname']}_{scoring}_out.pdbqt",
                                        exhaustiveness=redock_exh, num_modes=n_modes, seed=seed)
                    if rd.ok:
                        rr = ctx.tools.call("docking.pose_rmsd_all_models", agent=self.name,
                                            reference_pdb=box["ligand_pdb"],
                                            pose_pdbqt=rd.data["out_pdbqt"])
                        if rr.ok:
                            dd = rr.data
                            validation = {"performed": True, "ligand": box["resname"],
                                          "redock_rmsd_A": dd["top1_rmsd_A"],
                                          "best_pose_rmsd_A": dd["best_rmsd_A"],
                                          "best_pose_rank": dd["best_rmsd_rank"],
                                          "redock_score": rd.data["best_score_kcal_per_mol"],
                                          "success_threshold_A": 2.0,
                                          "passes": dd["top1_success"],
                                          "sampled_near_native": dd["sampled_near_native"],
                                          "diagnosis": dd["diagnosis"],
                                          "exhaustiveness": redock_exh,
                                          "method": dd["method"]}
                            ev.append(self.ev(ctx, "COMPUTED", "redocking_rmsd_top1",
                                              dd["top1_rmsd_A"], call=rr, units="A",
                                              subject=f"{rec['pdb_id']}:{box['resname']}",
                                              validation={"success_threshold_A": 2.0,
                                                          "exhaustiveness": redock_exh,
                                                          "scoring_function":
                                                              rd.data.get("scoring_function")},
                                              note=f"co-crystal ligand re-docked into the same "
                                                   f"prepared receptor with the "
                                                   f"{rd.data.get('scoring_function')} scoring "
                                                   f"function at exhaustiveness {redock_exh}; "
                                                   f"<=2 A is the usual convention"))
                            ev.append(self.ev(ctx, "COMPUTED", "redocking_rmsd_best_of_modes",
                                              dd["best_rmsd_A"], call=rr, units="A",
                                              subject=f"{rec['pdb_id']}:{box['resname']}",
                                              validation={"best_rmsd_rank": dd["best_rmsd_rank"],
                                                          "n_poses": dd["n_poses"],
                                                          "scoring_function":
                                                              rd.data.get("scoring_function")},
                                              note=dd["diagnosis"]))
        if not validation["performed"]:
            ctx.degrade("docking ran without redocking validation (no co-crystal reference "
                        "available); scores are unvalidated for this receptor")

        enrich = self._receptor_enrichment(rec["pdb_id"], scoring)
        if enrich:
            validation["enrichment"] = enrich
            ci = enrich.get("auc_ci95")
            ev.append(self.ev(ctx, "COMPUTED", "docking_enrichment_roc_auc", enrich["roc_auc"],
                              tool="aletheia.docking_validation", tool_version="1.0",
                              params_hash=f"{rec['pdb_id']}:{scoring}:"
                                          f"{enrich['n_actives']}a/{enrich['n_decoys']}d",
                              subject=f"{rec['pdb_id']}:{scoring}", validation=enrich,
                              note=f"{enrich['n_actives']} actives vs {enrich['n_decoys']} "
                                   f"{enrich.get('decoy_class', 'decoys')} docked into this "
                                   f"receptor with the {scoring} scoring function"
                                   + (f"; 95% CI {ci}" if ci else "")
                                   + (f"; {enrich['limitation']}" if enrich.get("limitation")
                                      else "")))
            ctx.note("docking_oracle_validated", bool(enrich["usable_for_ranking"]))
            if enrich.get("ordering_inverted"):
                ctx.degrade(
                    f"on {rec['pdb_id']} the {scoring} ordering is INVERTED: measured inactives "
                    f"score {enrich['score_gap']} kcal/mol better than actives, so a better score "
                    f"here is evidence of nothing; ranking on this oracle is disabled")
            elif not enrich["usable_for_ranking"]:
                ctx.degrade(
                    f"on {rec['pdb_id']} the {scoring} setup does not separate actives from "
                    f"measured inactives (ROC AUC {enrich['roc_auc']}, 95% CI {ci}); the scores "
                    f"below are geometry-driven numbers and must not be read as a potency "
                    f"ranking, and ranking on this oracle is disabled")
        else:
            ctx.note("docking_oracle_validated", False)
            ctx.degrade(f"no measured enrichment exists for {rec['pdb_id']} with the {scoring} "
                        f"scoring function; its scores cannot drive ranking")

        # -- candidates -------------------------------------------------------
        smiles_in = list(step.inputs.get("smiles") or [])
        cands = ctx.blackboard.get("candidates", [])
        if smiles_in:
            from rdkit import Chem
            targets = [{"cand_id": f"U{i}", "smiles": Chem.MolToSmiles(Chem.MolFromSmiles(s))}
                       for i, s in enumerate(smiles_in, 1) if Chem.MolFromSmiles(s)]
        else:
            ranked = sorted(cands, key=lambda c: -(c.get("properties", {}).get("QED") or 0))
            targets = [{"cand_id": c["cand_id"], "smiles": c["smiles"]}
                       for c in ranked[: int(step.inputs.get("max_dock", 8))]]
        if not targets:
            return self.fail(step, "no molecules to dock", t0)

        results = []
        for tgt in targets:
            lp = ctx.tools.call("docking.prepare_ligand", agent=self.name, smiles=tgt["smiles"],
                                out_pdbqt=f"cache/docking/{tgt['cand_id']}.pdbqt", seed=seed)
            if not lp.ok:
                ctx.degrade(f"ligand preparation failed for {tgt['cand_id']}: {lp.error}")
                continue
            dk = ctx.tools.call("docking.vina_dock", scoring=scoring, agent=self.name,
                                receptor_pdbqt=rec["rec_pdbqt"], ligand_pdbqt=lp.data["path"],
                                center=box["center"], size=box["size"],
                                out_pdbqt=f"cache/docking/{tgt['cand_id']}_{scoring}_out.pdbqt",
                                exhaustiveness=exh, num_modes=n_modes, seed=seed)
            if not dk.ok:
                ctx.degrade(f"docking failed for {tgt['cand_id']}: {dk.error}")
                continue
            score = dk.data["best_score_kcal_per_mol"]
            e = self.ev(ctx, "COMPUTED", "vina_score", score, call=dk, units="kcal/mol",
                        subject=tgt["smiles"],
                        validation={k: v for k, v in validation.items() if k in
                                    ("redock_rmsd_A", "passes", "ligand")} or {"redocking": "not performed"},
                        note=f"AutoDock Vina {dk.data['vina_version']}, exhaustiveness={exh}, "
                             f"seed={seed}, box from {box['origin']}; a docking score, not an "
                             "experimental affinity")
            ct = ctx.tools.call("docking.contacts", agent=self.name, receptor_pdb=rec["rec_pdb"],
                                pose_pdbqt=dk.data["out_pdbqt"], model_index=0)
            contact_info = {}
            if ct.ok:
                contact_info = {"n_polar": ct.data["n_polar_contacts"],
                                "residues": ct.data["contact_residues"][:10]}
                self.ev(ctx, "COMPUTED", "n_polar_contacts", ct.data["n_polar_contacts"], call=ct,
                        subject=tgt["smiles"],
                        note=f"{ct.data['method']}; residues: "
                             f"{', '.join(ct.data['contact_residues'][:6])}")
            ev.append(e)
            results.append({"cand_id": tgt["cand_id"], "smiles": tgt["smiles"], "score": score,
                            "claim_id": e.claim_id, "pose": dk.data["out_pdbqt"],
                            "contacts": contact_info})
            for c in cands:
                if c["smiles"] == tgt["smiles"]:
                    c.setdefault("scores", {})["vina_score"] = score
                    c.setdefault("score_claims", {})["vina_score"] = e.claim_id
                    c.setdefault("properties", {})["vina_score"] = score
        if cands:
            ctx.note("candidates", cands)
        if results:
            best = min(results, key=lambda r: r["score"])
            ev.append(self.ev(ctx, "COMPUTED", "best_vina_score", best["score"],
                              tool="aletheia.docking_agent", tool_version="1.0",
                              params_hash=f"n={len(results)}", units="kcal/mol",
                              subject=best["smiles"],
                              note=f"best of {len(results)} docked molecules"))
        ctx.note("docking", {"receptor": rec["rec_pdbqt"], "box": {k: box[k] for k in
                                                                   ("center", "size", "origin")},
                             "validation": validation, "results": results,
                             "params": {"exhaustiveness": exh, "seed": seed, "num_modes": n_modes}})
        msgs = [f"docked {len(results)} molecule(s) into {rec['pdb_id']}"]
        if validation["performed"]:
            msgs.append(f"redocking top-1 RMSD {validation['redock_rmsd_A']} A "
                        f"({'passes' if validation['passes'] else 'FAILS'} the 2 A convention); "
                        f"best of {int(n_modes)} poses {validation['best_pose_rmsd_A']} A at rank "
                        f"{validation['best_pose_rank']} — {validation['diagnosis']}")
            if not validation["passes"]:
                ctx.degrade(f"redocking did not reproduce the crystal pose at rank 1 "
                            f"(top-1 RMSD {validation['redock_rmsd_A']} A); "
                            f"{validation['diagnosis']}")
        else:
            msgs.append("no redocking validation available for this receptor")
        return AgentResult(agent=self.name, step_id=step.step_id, evidence=ev,
                           data={"results": results, "validation": validation,
                                 "box": {k: box[k] for k in ("center", "size", "origin")}},
                           degraded=not validation["performed"], messages=msgs,
                           duration_s=round(time.time() - t0, 3))
