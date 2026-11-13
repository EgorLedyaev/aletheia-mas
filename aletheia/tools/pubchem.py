"""PubChem PUG-REST tools (name -> structure, CID records, synonyms)."""
from __future__ import annotations

from typing import Any, Dict, List

from ..core.provenance import utcnow
from .http import get_json

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
VERSION = "pug-rest"
LICENSE = "Public domain (NCBI); depositor terms vary"
# PubChem renamed SMILES properties; ask for several spellings and use whichever comes back.
SMILES_KEYS = ("SMILES", "CanonicalSMILES", "ConnectivitySMILES", "IsomericSMILES")
PROPS = "MolecularFormula,MolecularWeight,XLogP,TPSA,HBondDonorCount,HBondAcceptorCount,IUPACName"


def _first_smiles(rec: Dict[str, Any]) -> Any:
    for k in SMILES_KEYS:
        if rec.get(k):
            return rec[k]
    return None


def compound_by_name(name: str) -> Dict[str, Any]:
    """Resolve a compound name to CID + structure + PubChem-computed properties."""
    try:
        d = get_json(f"{BASE}/compound/name/{name}/property/{PROPS},SMILES/JSON")
    except RuntimeError:
        d = get_json(f"{BASE}/compound/name/{name}/property/{PROPS},CanonicalSMILES/JSON")
    recs = d.get("PropertyTable", {}).get("Properties", [])
    if not recs:
        raise FileNotFoundError(f"PubChem has no compound named {name!r}")
    r = recs[0]
    return {"query": name, "cid": r.get("CID"), "smiles": _first_smiles(r),
            "iupac_name": r.get("IUPACName"), "formula": r.get("MolecularFormula"),
            "pubchem_properties": {k: r.get(k) for k in
                                   ("MolecularWeight", "XLogP", "TPSA",
                                    "HBondDonorCount", "HBondAcceptorCount")},
            "retrieved_at": utcnow(),
            "source_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{r.get('CID')}"}


def compound_by_cid(cid: int) -> Dict[str, Any]:
    """Fetch one CID record."""
    d = get_json(f"{BASE}/compound/cid/{cid}/property/{PROPS},SMILES/JSON")
    r = d["PropertyTable"]["Properties"][0]
    return {"cid": r.get("CID"), "smiles": _first_smiles(r), "formula": r.get("MolecularFormula"),
            "iupac_name": r.get("IUPACName"),
            "pubchem_properties": {k: r.get(k) for k in
                                   ("MolecularWeight", "XLogP", "TPSA",
                                    "HBondDonorCount", "HBondAcceptorCount")},
            "retrieved_at": utcnow(),
            "source_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"}


def synonyms(cid: int, limit: int = 12) -> Dict[str, Any]:
    """Depositor-supplied synonyms for a CID."""
    d = get_json(f"{BASE}/compound/cid/{cid}/synonyms/JSON")
    syns: List[str] = d.get("InformationList", {}).get("Information", [{}])[0].get("Synonym", [])
    return {"cid": cid, "synonyms": syns[:limit], "n_synonyms": len(syns),
            "retrieved_at": utcnow(),
            "source_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}#section=Names"}


def register(registry, config):
    t = registry.tool
    t("pubchem.compound_by_name", VERSION, license=LICENSE, default_tag="RETRIEVED",
      network=True, schema={"name": "str"})(compound_by_name)
    t("pubchem.compound_by_cid", VERSION, license=LICENSE, default_tag="RETRIEVED",
      network=True, schema={"cid": "int"})(compound_by_cid)
    t("pubchem.synonyms", VERSION, license=LICENSE, default_tag="RETRIEVED", network=True,
      schema={"cid": "int"})(synonyms)
    return registry
