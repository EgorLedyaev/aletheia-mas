"""ChEMBL web-services tools. Records are RETRIEVED evidence: accession + retrieval date."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..core.provenance import utcnow
from .http import get_json

BASE = "https://www.ebi.ac.uk/chembl/api/data"
VERSION = "ws-2.x"          # replaced at runtime by the live release in `status()`
LICENSE = "CC BY-SA 3.0"


def status() -> Dict[str, Any]:
    """ChEMBL release and API availability."""
    d = get_json(f"{BASE}/status.json")
    return {"chembl_release": d.get("chembl_db_version"), "api_status": d.get("status"),
            "retrieved_at": utcnow(), "source_url": f"{BASE}/status.json"}


def target_by_accession(accession: str) -> Dict[str, Any]:
    """Map a UniProt accession to ChEMBL targets (single-protein preferred)."""
    d = get_json(f"{BASE}/target.json",
                 {"target_components__accession": accession, "limit": 20})
    out = []
    for t in d.get("targets", []):
        out.append({"target_chembl_id": t.get("target_chembl_id"),
                    "pref_name": t.get("pref_name"), "type": t.get("target_type"),
                    "organism": t.get("organism"),
                    "accessions": [c.get("accession") for c in t.get("target_components", [])]})
    single = [t for t in out if t["type"] == "SINGLE PROTEIN"]
    return {"accession": accession, "targets": out, "n_targets": len(out),
            "preferred": (single or out or [None])[0],
            "retrieved_at": utcnow(), "source_url": f"{BASE}/target.json?target_components__accession={accession}"}


def activities(target_chembl_id: str, standard_types: Optional[List[str]] = None,
               limit: int = 400, min_pchembl: float = 0.0) -> Dict[str, Any]:
    """Bioactivities for a target: exact-relation, pChEMBL-valued records only.

    We deliberately keep only `standard_relation == '='` records with a pChEMBL value, so the
    downstream QSAR set contains no censored ('>' / '<') measurements silently treated as exact.
    """
    standard_types = standard_types or ["IC50", "Ki", "Kd", "EC50"]
    rows: List[Dict[str, Any]] = []
    dropped = {"no_pchembl": 0, "censored": 0, "no_smiles": 0}
    offset, page = 0, min(200, limit)
    while len(rows) < limit:
        d = get_json(f"{BASE}/activity.json", {
            "target_chembl_id": target_chembl_id,
            "standard_type__in": ",".join(standard_types),
            "limit": page, "offset": offset})
        acts = d.get("activities", [])
        if not acts:
            break
        for a in acts:
            if a.get("standard_relation") not in ("=", None):
                dropped["censored"] += 1
                continue
            if a.get("pchembl_value") in (None, ""):
                dropped["no_pchembl"] += 1
                continue
            smi = a.get("canonical_smiles")
            if not smi:
                dropped["no_smiles"] += 1
                continue
            rows.append({
                "molecule_chembl_id": a.get("molecule_chembl_id"),
                "smiles": smi,
                "standard_type": a.get("standard_type"),
                "standard_value": a.get("standard_value"),
                "standard_units": a.get("standard_units"),
                "pchembl_value": float(a["pchembl_value"]),
                "assay_chembl_id": a.get("assay_chembl_id"),
                "assay_type": a.get("assay_type"),
                "document_chembl_id": a.get("document_chembl_id"),
                "target_chembl_id": a.get("target_chembl_id"),
            })
        offset += page
        if offset >= int(d.get("page_meta", {}).get("total_count", 0) or 0):
            break
    if min_pchembl:
        rows = [r for r in rows if r["pchembl_value"] >= min_pchembl]
    # one record per molecule: median pChEMBL across assays
    by_mol: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_mol.setdefault(r["molecule_chembl_id"], []).append(r)
    import statistics
    uniq = []
    for mid, rs in by_mol.items():
        vals = [r["pchembl_value"] for r in rs]
        uniq.append({**rs[0], "pchembl_value": round(statistics.median(vals), 3),
                     "n_measurements": len(rs),
                     "pchembl_spread": round(max(vals) - min(vals), 3)})
    uniq.sort(key=lambda r: -r["pchembl_value"])
    return {"target_chembl_id": target_chembl_id, "n_activity_rows": len(rows),
            "n_unique_molecules": len(uniq), "dropped": dropped,
            "standard_types": standard_types, "activities": uniq,
            "retrieved_at": utcnow(),
            "source_url": f"{BASE}/activity.json?target_chembl_id={target_chembl_id}"}


def molecule(chembl_id: str) -> Dict[str, Any]:
    """One ChEMBL molecule record (structure, properties, development phase)."""
    d = get_json(f"{BASE}/molecule/{chembl_id}.json")
    st = d.get("molecule_structures") or {}
    props = d.get("molecule_properties") or {}
    return {"molecule_chembl_id": d.get("molecule_chembl_id"),
            "pref_name": d.get("pref_name"),
            "smiles": st.get("canonical_smiles"), "inchikey": st.get("standard_inchi_key"),
            "max_phase": d.get("max_phase"), "molecule_type": d.get("molecule_type"),
            "first_approval": d.get("first_approval"),
            "chembl_properties": {k: props.get(k) for k in
                                  ("full_mwt", "alogp", "psa", "hba", "hbd", "qed_weighted",
                                   "num_ro5_violations", "cx_most_apka", "cx_most_bpka")},
            "retrieved_at": utcnow(), "source_url": f"{BASE}/molecule/{chembl_id}"}


def search_molecule(name: str, limit: int = 5) -> Dict[str, Any]:
    """Free-text molecule search (pref_name / synonym)."""
    d = get_json(f"{BASE}/molecule/search.json", {"q": name, "limit": limit})
    out = []
    for m in d.get("molecules", []):
        st = m.get("molecule_structures") or {}
        out.append({"molecule_chembl_id": m.get("molecule_chembl_id"),
                    "pref_name": m.get("pref_name"), "smiles": st.get("canonical_smiles"),
                    "max_phase": m.get("max_phase")})
    return {"query": name, "hits": out, "n_hits": len(out), "retrieved_at": utcnow(),
            "source_url": f"{BASE}/molecule/search.json?q={name}"}


def register(registry, config):
    t = registry.tool
    t("chembl.status", VERSION, license=LICENSE, default_tag="RETRIEVED", network=True)(status)
    t("chembl.target_by_accession", VERSION, license=LICENSE, default_tag="RETRIEVED",
      network=True, schema={"accession": "str"})(target_by_accession)
    t("chembl.activities", VERSION, license=LICENSE, default_tag="RETRIEVED", network=True,
      cost_hint="medium", schema={"target_chembl_id": "str", "limit": "int"})(activities)
    t("chembl.molecule", VERSION, license=LICENSE, default_tag="RETRIEVED", network=True,
      schema={"chembl_id": "str"})(molecule)
    t("chembl.search_molecule", VERSION, license=LICENSE, default_tag="RETRIEVED", network=True,
      schema={"name": "str"})(search_molecule)
    return registry
