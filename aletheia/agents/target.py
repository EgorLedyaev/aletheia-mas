"""Target / Protein Analyst agent.

Responsibilities
  * resolve whatever the user wrote (gene symbol, UniProt accession, PDB id) to a verified identity
  * run identity checks that *block* ID-structure mismatches before any docking happens
  * choose a structure (highest-resolution X-ray with a bound ligand) or fall back to AlphaFold DB
  * define a binding site: co-crystal ligand centroid when available, otherwise a LIGSITE-style
    buriedness grid -- and report which of the two was used
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Optional, Tuple

from ..core.contracts import AgentResult, TargetCard
from ..core.context import RunContext
from .base import Agent

UNIPROT_RE = re.compile(r"^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9][A-Z][A-Z0-9]{2}[0-9])$")
PDB_RE = re.compile(r"^[0-9][A-Za-z0-9]{3}$")


def _classify(token: str) -> str:
    t = token.strip()
    if UNIPROT_RE.match(t.upper()):
        return "accession"
    if PDB_RE.match(t):
        return "pdb"
    return "gene"


def _seq_identity(a: str, b: str, k: int = 12) -> Dict[str, Any]:
    """Best-offset identity between two sequences (no gaps): quick consistency check."""
    if not a or not b:
        return {"identity": None, "note": "missing sequence"}
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    best = (0, 0, 0)
    probe = short[: min(len(short), 60)]
    starts = [long_.find(probe[i:i + k]) - i for i in range(0, max(1, len(probe) - k), 4)]
    cands = sorted({s for s in starts if s > -len(long_)}) or [0]
    for off in cands:
        matches = total = 0
        for i, ch in enumerate(short):
            j = i + off
            if 0 <= j < len(long_):
                total += 1
                matches += (ch == long_[j])
        if total and matches / total > best[0]:
            best = (matches / total, matches, total)
    return {"identity": round(best[0], 4), "n_matched": best[1], "n_compared": best[2],
            "method": "best-offset ungapped comparison"}


class TargetAnalystAgent(Agent):
    name = "target_analyst"
    description = "Resolves target identity, validates it, picks a structure and a binding site."
    tools = ["uniprot.search_gene", "uniprot.entry", "uniprot.sequence_features", "pdb.entry",
             "pdb.download", "pdb.ligands", "pdb.chain_sequences", "pdb.extract_receptor",
             "pdb.extract_ligand", "alphafold.prediction", "alphafold.download_model",
             "alphafold.plddt_summary", "pocket.detect"]

    # -- resolution ----------------------------------------------------------
    def _resolve_accession(self, ctx: RunContext, tokens: List[str]) -> Tuple[Optional[str], List[str], Optional[str]]:
        accession, pdb_hint, gene = None, [], None
        for tok in tokens:
            kind = _classify(tok)
            if kind == "accession" and not accession:
                accession = tok.upper()
            elif kind == "pdb":
                pdb_hint.append(tok.upper())
            elif kind == "gene" and not gene:
                gene = tok.upper()
        if accession is None and gene:
            c = ctx.tools.call("uniprot.search_gene", agent=self.name, gene=gene, organism_id=9606)
            if c.ok and c.data.get("hits"):
                accession = c.data["hits"][0]["accession"]
                self.ev(ctx, "RETRIEVED", "gene_to_accession", accession, call=c,
                        subject=gene, source_id=accession,
                        source_url=c.data.get("source_url"),
                        retrieved_at=c.data.get("retrieved_at"),
                        note=f"first reviewed human hit for gene {gene}")
            else:
                ctx.degrade(f"UniProt gene search failed for {gene}: {c.error}")
        if accession is None and pdb_hint:
            # reverse-map a PDB id to UniProt via the cross-reference index
            from ..tools.http import get_json
            try:
                d = get_json("https://rest.uniprot.org/uniprotkb/search",
                             {"query": f"xref:pdb-{pdb_hint[0]}", "fields": "accession",
                              "size": 1, "format": "json"})
                if d.get("results"):
                    accession = d["results"][0]["primaryAccession"]
            except Exception as exc:
                ctx.degrade(f"PDB->UniProt reverse mapping failed: {type(exc).__name__}")
        return accession, pdb_hint, gene

    # -- structure choice ----------------------------------------------------
    @staticmethod
    def _ranked_structures(pdb_entries: List[Dict[str, Any]], hint: List[str]) -> List[Dict[str, Any]]:
        """Candidate structures, best first. Hinted id wins; otherwise X-ray by resolution."""
        if hint:
            for e in pdb_entries:
                if e["pdb_id"].upper() == hint[0].upper():
                    return [e]
            return [{"pdb_id": hint[0].upper(), "method": None, "resolution": None, "chains": None}]
        scored = []
        for e in pdb_entries:
            try:
                res = float(str(e.get("resolution") or "").split()[0])
            except (ValueError, IndexError):
                continue
            if (e.get("method") or "").upper().startswith("X-RAY"):
                scored.append((res, e))
        scored.sort(key=lambda t: t[0])
        return [e for _, e in scored] or list(pdb_entries)

    @staticmethod
    def _canonical(smiles: str):
        from rdkit import Chem, RDLogger
        RDLogger.DisableLog("rdApp.*")
        m = Chem.MolFromSmiles(smiles or "")
        if m is None:
            return None
        return Chem.MolToSmiles(m, isomericSmiles=False)

    def _entry_matching_ligand(self, ctx: RunContext, ranked: List[Dict[str, Any]],
                               want_smiles: str, max_entries: int = 12):
        """Find a cross-referenced entry whose co-crystal ligand IS the requested molecule.

        Structure choice used to ignore a ligand named in the request and return the
        highest-resolution entry instead -- so "which PDB has EGFR with erlotinib bound?" answered
        with the wrong structure (W4 baseline study, docs/negative_results.md N9). The match is on
        canonical SMILES of the PDB chemical component, not on names.
        """
        self._lig_call = None
        want = self._canonical(want_smiles)
        if not want:
            return None, None
        # First ask RCSB which entries actually contain this ligand, then keep only those that are
        # cross-referenced to this accession. Scanning candidates by resolution misses the answer:
        # the erlotinib complex 1M17 sits at 2.6 A among several hundred EGFR structures.
        srch = ctx.tools.call("pdb.search_by_ligand_smiles", agent=self.name, smiles=want_smiles)
        if srch.ok and srch.data.get("entry_ids"):
            hits = {e.upper() for e in srch.data["entry_ids"]}
            comps = (srch.data.get("component_ids") or [None])[0]
            for e in ranked:
                if e["pdb_id"].upper() in hits:
                    self._lig_call = srch
                    return e, comps
        seen: Dict[str, Optional[str]] = {}
        for e in ranked[:max_entries]:
            pe = ctx.tools.call("pdb.entry", agent=self.name, entry_id=e["pdb_id"])
            if not pe.ok:
                continue
            for comp in (pe.data.get("ligand_ids") or [])[:6]:
                if comp not in seen:
                    cc = ctx.tools.call("pdb.chemcomp", agent=self.name, comp_id=comp)
                    seen[comp] = self._canonical(cc.data.get("smiles")) if cc.ok else None
                if seen[comp] and seen[comp] == want:
                    self._lig_call = cc
                    return e, comp
        return None, None

    def _select_with_ligand(self, ctx: RunContext, ranked: List[Dict[str, Any]],
                            max_tries: int = 4, min_ligand_atoms: int = 12):
        """Prefer a high-resolution structure that actually has a drug-like ligand bound.

        A structure-based campaign needs a defined site; an apo structure forces the pocket
        finder. We therefore inspect up to `max_tries` structures and take the first with a
        co-crystal ligand of at least `min_ligand_atoms` heavy atoms, falling back to the
        highest-resolution entry if none has one.
        """
        fallback = None
        for e in ranked[:max_tries]:
            dl = ctx.tools.call("pdb.download", agent=self.name, entry_id=e["pdb_id"])
            if not dl.ok:
                continue
            lg = ctx.tools.call("pdb.ligands", agent=self.name, pdb_path=dl.data["path"])
            if fallback is None:
                fallback = (e, dl, lg)
            if lg.ok and lg.data.get("largest") and \
                    lg.data["largest"]["n_heavy_atoms"] >= min_ligand_atoms:
                return e, dl, lg
        return fallback if fallback else (None, None, None)

    def act(self, ctx: RunContext, step) -> AgentResult:
        t0 = time.time()
        tokens = list(step.inputs.get("targets") or []) or list(ctx.blackboard.get("targets") or [])
        need_structure = bool(step.inputs.get("need_structure", True))
        if not tokens:
            return self.fail(step, "no target was named in the request", t0)

        accession, pdb_hint, gene = self._resolve_accession(ctx, tokens)
        if not accession:
            return self.fail(step, f"could not resolve {tokens} to a UniProt accession", t0)

        c = ctx.tools.call("uniprot.entry", agent=self.name, accession=accession)
        if not c.ok:
            return self.fail(step, f"UniProt lookup failed for {accession}: {c.error}", t0)
        u = c.data
        card = TargetCard(accession=u["accession"], gene=(u["genes"] or [gene])[0] if (u["genes"] or gene) else None,
                          name=u["protein_name"], organism=u["organism"], length=u["length"],
                          sequence=u["sequence"], pdb_ids=u["pdb_ids"])
        ev = [
            self.ev(ctx, "RETRIEVED", "uniprot_protein_name", u["protein_name"], call=c,
                    subject=u["accession"], source_id=u["accession"],
                    source_url=u["source_url"], retrieved_at=u["retrieved_at"]),
            self.ev(ctx, "RETRIEVED", "sequence_length", u["length"], call=c, units="residues",
                    subject=u["accession"], source_id=u["accession"],
                    source_url=u["source_url"], retrieved_at=u["retrieved_at"]),
            self.ev(ctx, "RETRIEVED", "n_pdb_structures", len(u["pdb_ids"]), call=c,
                    subject=u["accession"], source_id=u["accession"],
                    source_url=u["source_url"], retrieved_at=u["retrieved_at"]),
        ]
        card.claims["protein_name"] = ev[0].claim_id
        card.claims["length"] = ev[1].claim_id
        card.claims["n_pdb"] = ev[2].claim_id

        # identity check 1: internal consistency of the record
        checks: List[Dict[str, Any]] = []
        consistent = bool(u["sequence"]) and len(u["sequence"]) == u["length"]
        checks.append({"check": "uniprot_length_matches_sequence", "pass": consistent,
                       "detail": f"len(sequence)={len(u['sequence'] or '')} vs length={u['length']}"})
        # identity check 2: requested PDB really belongs to this accession
        if pdb_hint:
            belongs = pdb_hint[0].upper() in {p.upper() for p in u["pdb_ids"]}
            checks.append({"check": "pdb_belongs_to_accession", "pass": belongs,
                           "detail": f"{pdb_hint[0]} in UniProt cross-references of {accession}: {belongs}"})
            if not belongs:
                ctx.degrade(f"identity check failed: {pdb_hint[0]} is not cross-referenced to "
                            f"{accession}; structure-based steps are blocked")

        # The ChEMBL target id is part of this target's identity, so it is resolved here rather
        # than only inside the chemistry retriever -- a target brief used to omit it entirely
        # (W4 baseline study, docs/negative_results.md N9). Optional: if ChEMBL is unreachable the
        # run degrades instead of failing.
        ct = ctx.tools.call("chembl.target_by_accession", agent=self.name, accession=accession)
        if ct.ok and (ct.data.get("preferred") or {}).get("target_chembl_id"):
            pref = ct.data["preferred"]
            ev.append(self.ev(ctx, "RETRIEVED", "chembl_target_id", pref["target_chembl_id"],
                              call=ct, subject=accession, source_id=pref["target_chembl_id"],
                              retrieved_at=ct.data.get("retrieved_at"),
                              note=f"ChEMBL target for {accession}"))
            card.claims["chembl_target_id"] = ev[-1].claim_id
        else:
            ctx.degrade("ChEMBL target id not resolved for this accession "
                        f"({ct.error or 'no preferred target'})")

        seq_feat = ctx.tools.call("uniprot.sequence_features", agent=self.name, sequence=u["sequence"] or "")
        if seq_feat.ok:
            ev.append(self.ev(ctx, "COMPUTED", "sequence_gravy", seq_feat.data["gravy"], call=seq_feat,
                              subject=accession, note="Kyte-Doolittle mean hydropathy"))
            ev.append(self.ev(ctx, "COMPUTED", "net_charge_ph7", seq_feat.data["net_charge_ph7"],
                              call=seq_feat, subject=accession,
                              note="K+R-D-E count, no pKa model"))

        structure_ok = all(ch["pass"] for ch in checks)
        if need_structure and structure_ok:
            ranked = self._ranked_structures(u["pdb_entries"], pdb_hint)
            want_lig = step.inputs.get("ligand")
            matched_comp = None
            if want_lig and not pdb_hint:
                lig_smiles = want_lig if self._canonical(want_lig) else None
                if lig_smiles is None:
                    pc = ctx.tools.call("pubchem.compound_by_name", agent=self.name, name=want_lig)
                    lig_smiles = pc.data.get("smiles") if pc.ok else None
                if lig_smiles:
                    hit, matched_comp = self._entry_matching_ligand(ctx, ranked, lig_smiles)
                    if hit is not None:
                        ranked = [hit] + [e for e in ranked if e["pdb_id"] != hit["pdb_id"]]
                    else:
                        ctx.degrade(f"no cross-referenced structure in the first candidates has "
                                    f"'{want_lig}' bound; selecting by resolution instead")
            pick, dl, lg = self._select_with_ligand(ctx, ranked)
            if pick:
                card.chosen_pdb = pick["pdb_id"]
                pe = ctx.tools.call("pdb.entry", agent=self.name, entry_id=pick["pdb_id"])
                if pe.ok:
                    ev.append(self.ev(ctx, "RETRIEVED", "pdb_resolution", pe.data["resolution_A"],
                                      call=pe, units="A", subject=pick["pdb_id"],
                                      source_id=pick["pdb_id"], source_url=pe.data["source_url"],
                                      retrieved_at=pe.data["retrieved_at"]))
                    card.claims["resolution"] = ev[-1].claim_id
                if matched_comp and getattr(self, "_lig_call", None) is not None:
                    ev.append(self.ev(ctx, "RETRIEVED", "structure_chosen_by_ligand_match",
                                      pick["pdb_id"], call=self._lig_call,
                                      subject=matched_comp, source_id=matched_comp,
                                      retrieved_at=self._lig_call.data.get("retrieved_at"),
                                      note=f"selected because its co-crystal component "
                                           f"{matched_comp} is the requested ligand "
                                           f"(canonical-SMILES match), not because of resolution"))
                if dl is not None and dl.ok:
                    chains = ctx.tools.call("pdb.chain_sequences", agent=self.name,
                                            pdb_path=dl.data["path"])
                    # identity check 3: structure chain sequence vs UniProt sequence
                    if chains.ok and u["sequence"]:
                        ident = {}
                        for ch_id, seq in chains.data["chains"].items():
                            ident[ch_id] = _seq_identity(seq, u["sequence"])["identity"]
                        best_chain = max(ident, key=lambda k: (ident[k] or 0)) if ident else None
                        best_id = ident.get(best_chain)
                        checks.append({"check": "structure_sequence_matches_uniprot",
                                       "pass": bool(best_id and best_id >= 0.9),
                                       "detail": f"best chain {best_chain} identity "
                                                 f"{best_id if best_id is not None else 'n/a'}"})
                        if best_id is not None:
                            ev.append(self.ev(ctx, "COMPUTED", "structure_sequence_identity",
                                              round(best_id, 4), call=chains,
                                              subject=f"{pick['pdb_id']}:{best_chain}",
                                              note="ungapped best-offset identity to the UniProt sequence"))
                        card.chosen_pdb = pick["pdb_id"]
                        ctx.note("receptor_chain", best_chain)
                    if lg.ok and lg.data["largest"]:
                        big = lg.data["largest"]
                        card.cocrystal_ligands = lg.data["ligands"][:5]
                        ev.append(self.ev(ctx, "COMPUTED", "cocrystal_ligand", big["resname"],
                                          call=lg, subject=pick["pdb_id"],
                                          note=f"{big['n_heavy_atoms']} heavy atoms, chain {big['chain']}"))
                        card.pocket = {"method": "cocrystal_ligand_centroid",
                                       "center": big["centroid"], "ligand": big["resname"],
                                       "chain": big["chain"],
                                       "claim": ev[-1].claim_id}
                        ctx.note("cocrystal", big)
                    ctx.note("receptor_pdb_path", dl.data["path"])
                    ctx.note("pdb_id", pick["pdb_id"])
                else:
                    ctx.degrade(f"PDB download failed for {pick['pdb_id']}: {dl.error}")
        elif need_structure:
            ctx.degrade("structure steps skipped: target identity checks did not pass")

        # AlphaFold is fetched when no experimental structure is usable
        if need_structure and not card.chosen_pdb:
            af = ctx.tools.call("alphafold.download_model", agent=self.name, accession=accession)
            if af.ok:
                pl = ctx.tools.call("alphafold.plddt_summary", agent=self.name, pdb_path=af.data["path"])
                card.alphafold = {"entry_id": af.data["entry_id"], "path": af.data["path"],
                                  "model_version": af.data["model_version"]}
                if pl.ok:
                    ev.append(self.ev(ctx, "COMPUTED", "alphafold_mean_plddt", pl.data["mean_plddt"],
                                      call=pl, subject=accession,
                                      note="per-residue model confidence, not accuracy"))
                    card.alphafold["mean_plddt"] = pl.data["mean_plddt"]
                ctx.note("receptor_pdb_path", af.data["path"])
            else:
                ctx.degrade(f"no usable structure: AlphaFold fetch failed ({af.error})")

        card.identity_checks = checks
        ctx.note("target_card", card.model_dump())
        ctx.note("targets", tokens)
        failed = [c for c in checks if not c["pass"]]
        return AgentResult(
            agent=self.name, step_id=step.step_id, ok=not failed, evidence=ev,
            data={"target": card.model_dump(), "identity_checks": checks},
            degraded=bool(failed),
            error=("identity check failed: " + "; ".join(c["check"] for c in failed)) if failed else None,
            messages=[f"{card.gene or accession}: {card.name}",
                      f"identity checks passed: {len(checks) - len(failed)}/{len(checks)}"],
            duration_s=round(time.time() - t0, 3))


class StructureAnalysisAgent(Agent):
    """Second action of the protein track: pocket detection and structure features."""
    name = "structure_analyst"
    description = "Binding-site detection on the selected structure."
    tools = ["pocket.detect"]

    def act(self, ctx: RunContext, step) -> AgentResult:
        t0 = time.time()
        path = ctx.blackboard.get("receptor_pdb_path")
        if not path:
            return self.fail(step, "no structure available for pocket detection", t0)
        coc = ctx.blackboard.get("cocrystal")
        ref = coc["centroid"] if coc else None
        c = ctx.tools.call("pocket.detect", agent=self.name, pdb_path=path, spacing=1.0,
                           probe=3.2, psp_min=5, reference_point=ref)
        if not c.ok:
            ctx.degrade(f"pocket detection failed: {c.error}")
            return self.fail(step, f"pocket detection failed: {c.error}", t0)
        d = c.data
        ev = []
        if d["top_pocket"]:
            ev.append(self.ev(ctx, "COMPUTED", "top_pocket_volume", d["top_pocket"]["volume_A3"],
                              call=c, units="A^3", subject=ctx.blackboard.get("pdb_id") or path,
                              validation=d.get("validation"),
                              note=d["method"]))
            ev.append(self.ev(ctx, "COMPUTED", "n_pockets_detected", d["n_pockets"], call=c,
                              subject=ctx.blackboard.get("pdb_id") or path))
        if d.get("validation"):
            ev.append(self.ev(ctx, "COMPUTED", "pocket_to_cocrystal_distance",
                              d["validation"]["best_pocket_nearest_point_distance_A"],
                              call=c, units="A",
                              subject=ctx.blackboard.get("pdb_id") or path,
                              note="distance from the nearest detected pocket centre to the "
                                   "crystallographic ligand centroid (localisation check)"))
        ctx.note("pockets", d["pockets"])
        return AgentResult(agent=self.name, step_id=step.step_id, evidence=ev,
                           data={"pockets": d["pockets"], "validation": d.get("validation"),
                                 "params": d["params"]},
                           messages=[f"{d['n_pockets']} buried cavities detected"],
                           duration_s=round(time.time() - t0, 3))
