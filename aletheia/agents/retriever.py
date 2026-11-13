"""Chemistry Retriever agent: known actives and compound identity from ChEMBL / PubChem.

Design point: design work must start from *measured* actives, not from what an LLM remembers
about a target. Every molecule this agent returns carries its ChEMBL id, the assay id it came
from and the retrieval date, so a reviewer can pull the same record.
"""
from __future__ import annotations

import statistics
import time
from typing import Any, Dict, List, Optional

from ..core.contracts import AgentResult, Candidate
from ..core.context import RunContext
from .base import Agent


class ChemistryRetrieverAgent(Agent):
    name = "chemistry_retriever"
    description = "Known actives, SAR summary and compound identity resolution."
    tools = ["chembl.status", "chembl.target_by_accession", "chembl.activities",
             "chembl.molecule", "chembl.search_molecule", "pubchem.compound_by_name",
             "rdkit.scaffold"]

    def resolve_molecule(self, ctx: RunContext, token: str) -> Optional[Dict[str, Any]]:
        """Resolve a user-supplied molecule name to a structure (PubChem first, then ChEMBL)."""
        from rdkit import Chem
        if Chem.MolFromSmiles(token):
            return {"smiles": Chem.MolToSmiles(Chem.MolFromSmiles(token)), "source": "user SMILES",
                    "source_id": None, "call": None}
        c = ctx.tools.call("pubchem.compound_by_name", agent=self.name, name=token)
        if c.ok and c.data.get("smiles"):
            return {"smiles": c.data["smiles"], "source": "PubChem",
                    "source_id": f"CID {c.data['cid']}", "source_url": c.data["source_url"],
                    "retrieved_at": c.data["retrieved_at"], "call": c}
        c2 = ctx.tools.call("chembl.search_molecule", agent=self.name, name=token)
        if c2.ok and c2.data.get("hits"):
            h = c2.data["hits"][0]
            if h.get("smiles"):
                return {"smiles": h["smiles"], "source": "ChEMBL",
                        "source_id": h["molecule_chembl_id"], "source_url": c2.data["source_url"],
                        "retrieved_at": c2.data["retrieved_at"], "call": c2}
        ctx.degrade(f"could not resolve molecule name {token!r} in PubChem or ChEMBL")
        return None

    def act(self, ctx: RunContext, step) -> AgentResult:
        t0 = time.time()
        card = ctx.blackboard.get("target_card") or {}
        accession = card.get("accession")
        limit = int(step.inputs.get("limit", 300))
        ev: List[Any] = []
        data: Dict[str, Any] = {}

        st = ctx.tools.call("chembl.status", agent=self.name)
        if st.ok:
            ev.append(self.ev(ctx, "RETRIEVED", "chembl_release", st.data["chembl_release"],
                              call=st, source_id=f"ChEMBL {st.data['chembl_release']}",
                              source_url=st.data["source_url"],
                              retrieved_at=st.data["retrieved_at"]))
            data["chembl_release"] = st.data["chembl_release"]

        if not accession:
            return self.fail(step, "no resolved target accession to query ChEMBL with", t0)

        tg = ctx.tools.call("chembl.target_by_accession", agent=self.name, accession=accession)
        if not tg.ok or not tg.data.get("preferred"):
            return self.fail(step, f"no ChEMBL target for {accession}: {tg.error}", t0)
        pref = tg.data["preferred"]
        ev.append(self.ev(ctx, "RETRIEVED", "chembl_target_id", pref["target_chembl_id"], call=tg,
                          subject=accession, source_id=pref["target_chembl_id"],
                          source_url=tg.data["source_url"], retrieved_at=tg.data["retrieved_at"],
                          note=pref.get("pref_name")))

        ac = ctx.tools.call("chembl.activities", agent=self.name,
                           target_chembl_id=pref["target_chembl_id"], limit=limit)
        if not ac.ok:
            ctx.degrade(f"ChEMBL activity query failed: {ac.error}")
            return AgentResult(agent=self.name, step_id=step.step_id, ok=False,
                               error=ac.error, evidence=ev, data=data, degraded=True,
                               duration_s=round(time.time() - t0, 3))
        acts = ac.data["activities"]
        ev.append(self.ev(ctx, "RETRIEVED", "n_unique_actives", ac.data["n_unique_molecules"],
                          call=ac, subject=pref["target_chembl_id"],
                          source_id=pref["target_chembl_id"], source_url=ac.data["source_url"],
                          retrieved_at=ac.data["retrieved_at"],
                          note=f"standard types {','.join(ac.data['standard_types'])}; "
                               f"censored records dropped: {ac.data['dropped']['censored']}"))
        if acts:
            vals = [a["pchembl_value"] for a in acts]
            ev.append(self.ev(ctx, "COMPUTED", "pchembl_median", round(statistics.median(vals), 3),
                              call=ac, subject=pref["target_chembl_id"],
                              note="median pChEMBL across unique molecules"))
            ev.append(self.ev(ctx, "COMPUTED", "pchembl_max", round(max(vals), 3), call=ac,
                              subject=pref["target_chembl_id"]))
            top = acts[0]
            ev.append(self.ev(ctx, "RETRIEVED", "most_potent_active", top["molecule_chembl_id"],
                              call=ac, subject=top["smiles"], source_id=top["molecule_chembl_id"],
                              source_url=f"https://www.ebi.ac.uk/chembl/compound_report_card/"
                                         f"{top['molecule_chembl_id']}/",
                              retrieved_at=ac.data["retrieved_at"],
                              note=f"pChEMBL {top['pchembl_value']} ({top['standard_type']})"))
            # scaffold summary over the top actives
            scafs: Dict[str, int] = {}
            for a in acts[:60]:
                sc = ctx.tools.call("rdkit.scaffold", agent=self.name, smiles=a["smiles"])
                if sc.ok:
                    scafs[sc.data["murcko_smiles"]] = scafs.get(sc.data["murcko_smiles"], 0) + 1
            common = sorted(scafs.items(), key=lambda kv: -kv[1])[:5]
            if common:
                ev.append(self.ev(ctx, "COMPUTED", "n_distinct_scaffolds_top60", len(scafs),
                                  tool="rdkit.scaffold", tool_version=sc.version,
                                  params_hash=sc.params_hash,
                                  subject=pref["target_chembl_id"],
                                  note="Bemis-Murcko scaffolds among the 60 most potent actives"))
            data["top_scaffolds"] = [{"scaffold": s, "count": n} for s, n in common]
        data.update({"target_chembl_id": pref["target_chembl_id"],
                     "target_pref_name": pref.get("pref_name"),
                     "n_unique_actives": ac.data["n_unique_molecules"],
                     "dropped": ac.data["dropped"],
                     "actives": acts[:200]})
        ctx.note("actives", acts)
        ctx.note("chembl_target", pref)
        return AgentResult(agent=self.name, step_id=step.step_id, evidence=ev, data=data,
                           messages=[f"{ac.data['n_unique_molecules']} unique actives "
                                     f"for {pref['target_chembl_id']}"],
                           duration_s=round(time.time() - t0, 3))
