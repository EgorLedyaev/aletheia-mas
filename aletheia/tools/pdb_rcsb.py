"""RCSB PDB tools: entry metadata (RETRIEVED) and geometry computed from the deposited file."""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional

from ..core.provenance import utcnow
from .http import get_json, get_text

DATA = "https://data.rcsb.org/rest/v1/core"
FILES = "https://files.rcsb.org/download"
VERSION = "rcsb-rest-v1"
LICENSE = "CC0 1.0 (PDB core data)"

# Residues that are solvent / buffer / cryoprotectant rather than a bound ligand of interest.
NON_LIGAND = {
    "HOH", "DOD", "WAT", "SO4", "PO4", "GOL", "EDO", "PEG", "PG4", "MPD", "DMS", "TRS", "ACT",
    "ACY", "FMT", "CL", "NA", "K", "MG", "CA", "ZN", "MN", "FE", "NI", "CU", "CD", "IOD", "BR",
    "NO3", "NH4", "EPE", "MES", "BME", "IMD", "AZI", "CO3", "SCN", "UNX", "UNL",
}


def entry(entry_id: str) -> Dict[str, Any]:
    """Entry-level metadata: title, method, resolution, entity counts."""
    eid = entry_id.upper()
    d = get_json(f"{DATA}/entry/{eid}")
    info = d.get("rcsb_entry_info", {})
    res = info.get("resolution_combined") or []
    return {"pdb_id": eid, "title": (d.get("struct") or {}).get("title"),
            "method": [m.get("method") for m in d.get("exptl", [])],
            "resolution_A": res[0] if res else None,
            "deposited": (d.get("rcsb_accession_info") or {}).get("deposit_date"),
            "released": (d.get("rcsb_accession_info") or {}).get("initial_release_date"),
            "polymer_entities": info.get("polymer_entity_count_protein"),
            "nonpolymer_entities": info.get("nonpolymer_entity_count"),
            "ligand_ids": info.get("nonpolymer_bound_components") or [],
            "retrieved_at": utcnow(), "source_url": f"https://www.rcsb.org/structure/{eid}"}


def download(entry_id: str, dest_dir: str = "cache/structures") -> Dict[str, Any]:
    """Download the deposited PDB-format coordinates; returns a local path + sha256."""
    eid = entry_id.upper()
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"{eid}.pdb")
    if not os.path.exists(path):
        text = get_text(f"{FILES}/{eid}.pdb")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    raw = open(path, "rb").read()
    n_atom = sum(1 for ln in raw.decode("utf-8", "ignore").splitlines()
                 if ln.startswith(("ATOM", "HETATM")))
    return {"pdb_id": eid, "path": path.replace("\\", "/"), "n_atom_records": n_atom,
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "retrieved_at": utcnow(), "source_url": f"{FILES}/{eid}.pdb"}


def _parse_atoms(path: str):
    for ln in open(path, "r", encoding="utf-8", errors="ignore"):
        if ln.startswith(("ATOM", "HETATM")):
            try:
                yield {"record": ln[:6].strip(), "name": ln[12:16].strip(),
                       "altloc": ln[16].strip(), "resname": ln[17:20].strip(),
                       "chain": ln[21].strip(), "resseq": ln[22:26].strip(),
                       "x": float(ln[30:38]), "y": float(ln[38:46]), "z": float(ln[46:54]),
                       "occ": float(ln[54:60] or 1.0), "bfac": float(ln[60:66] or 0.0),
                       "element": ln[76:78].strip()}
            except ValueError:
                continue


def ligands(pdb_path: str, min_atoms: int = 6) -> Dict[str, Any]:
    """Bound ligands with atom counts and centroids, computed from the coordinate file."""
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for a in _parse_atoms(pdb_path):
        if a["record"] != "HETATM" or a["resname"] in NON_LIGAND:
            continue
        groups.setdefault((a["resname"], a["chain"], a["resseq"]), []).append(a)
    out = []
    for (resname, chain, resseq), atoms in groups.items():
        heavy = [a for a in atoms if a["element"] != "H"]
        if len(heavy) < min_atoms:
            continue
        n = len(heavy)
        cx = sum(a["x"] for a in heavy) / n
        cy = sum(a["y"] for a in heavy) / n
        cz = sum(a["z"] for a in heavy) / n
        ext = [max(a[k] for a in heavy) - min(a[k] for a in heavy) for k in ("x", "y", "z")]
        out.append({"resname": resname, "chain": chain, "resseq": resseq, "n_heavy_atoms": n,
                    "centroid": [round(cx, 3), round(cy, 3), round(cz, 3)],
                    "extent_A": [round(e, 2) for e in ext]})
    out.sort(key=lambda r: -r["n_heavy_atoms"])
    return {"pdb_path": pdb_path, "n_ligands": len(out), "ligands": out,
            "largest": out[0] if out else None}


def chain_sequences(pdb_path: str) -> Dict[str, Any]:
    """One-letter sequences per chain, read from SEQRES records."""
    three2one = {"ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q",
                 "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
                 "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W",
                 "TYR": "Y", "VAL": "V", "MSE": "M", "SEC": "U", "PYL": "O"}
    seqs: Dict[str, List[str]] = {}
    for ln in open(pdb_path, "r", encoding="utf-8", errors="ignore"):
        if ln.startswith("SEQRES"):
            ch = ln[11]
            seqs.setdefault(ch, []).extend(three2one.get(r, "X") for r in ln[19:].split())
    return {"chains": {k: "".join(v) for k, v in seqs.items()},
            "lengths": {k: len(v) for k, v in seqs.items()}}


def extract_receptor(pdb_path: str, out_path: str, chain: Optional[str] = None,
                     keep_waters: bool = False) -> Dict[str, Any]:
    """Write a receptor-only PDB (protein atoms, optional single chain, altloc A)."""
    kept = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for ln in open(pdb_path, "r", encoding="utf-8", errors="ignore"):
            if ln.startswith("ATOM") or (ln.startswith("HETATM") and ln[17:20].strip() == "MSE"):
                if chain and ln[21].strip() != chain:
                    continue
                if ln[16].strip() not in ("", "A"):
                    continue
                out.write(ln)
                kept += 1
            elif keep_waters and ln.startswith("HETATM") and ln[17:20].strip() == "HOH":
                out.write(ln)
                kept += 1
        out.write("END\n")
    return {"path": out_path.replace("\\", "/"), "n_atoms": kept, "chain": chain,
            "sha256": hashlib.sha256(open(out_path, "rb").read()).hexdigest()}


def extract_ligand(pdb_path: str, resname: str, out_path: str,
                   chain: Optional[str] = None) -> Dict[str, Any]:
    """Write a single HET group to its own PDB (used as the redocking reference pose)."""
    kept = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for ln in open(pdb_path, "r", encoding="utf-8", errors="ignore"):
            if ln.startswith("HETATM") and ln[17:20].strip() == resname.upper():
                if chain and ln[21].strip() != chain:
                    continue
                if ln[16].strip() not in ("", "A"):
                    continue
                out.write(ln)
                kept += 1
        out.write("END\n")
    if kept == 0:
        raise ValueError(f"no HETATM records for {resname} in {pdb_path}")
    return {"path": out_path.replace("\\", "/"), "resname": resname.upper(), "n_atoms": kept}


def chemcomp(comp_id: str) -> Dict[str, Any]:
    """Chemical-component dictionary record for a ligand code (gives its SMILES)."""
    d = get_json(f"{DATA}/chemcomp/{comp_id.upper()}")
    info = d.get("chem_comp", {})
    smiles = None
    for desc in d.get("pdbx_chem_comp_descriptor", []):
        if desc.get("type") == "SMILES_CANONICAL" and desc.get("program") == "OpenEye OEToolkits":
            smiles = desc.get("descriptor")
            break
    if smiles is None:
        for desc in d.get("pdbx_chem_comp_descriptor", []):
            if desc.get("type", "").startswith("SMILES"):
                smiles = desc.get("descriptor")
                break
    return {"comp_id": comp_id.upper(), "name": info.get("name"),
            "formula": info.get("formula"), "formula_weight": info.get("formula_weight"),
            "smiles": smiles, "type": info.get("type"),
            "retrieved_at": utcnow(),
            "source_url": f"https://www.rcsb.org/ligand/{comp_id.upper()}"}


def search_by_ligand_smiles(smiles: str, rows: int = 25,
                            match_type: str = "graph-relaxed") -> Dict[str, Any]:
    """PDB entries whose co-crystal ligand matches a molecule, by chemical-structure search.

    Used when a request names the bound ligand ("EGFR with erlotinib bound"). Ranking structures
    by resolution and hoping the right ligand turns up does not work: the entry that holds a given
    ligand can sit anywhere in a target's several hundred structures.
    """
    import json as _json
    import urllib.parse as _up
    out: Dict[str, Any] = {"smiles": smiles, "match_type": match_type}
    for return_type, key in (("mol_definition", "component_ids"), ("entry", "entry_ids")):
        query = {"query": {"type": "terminal", "service": "chemical",
                           "parameters": {"value": smiles, "type": "descriptor",
                                          "descriptor_type": "SMILES",
                                          "match_type": match_type}},
                 "return_type": return_type,
                 "request_options": {"paginate": {"start": 0, "rows": rows}}}
        url = ("https://search.rcsb.org/rcsbsearch/v2/query?json="
               + _up.quote(_json.dumps(query)))
        try:
            d = get_json(url)
            out[key] = [r["identifier"] for r in d.get("result_set", [])]
        except Exception as exc:                       # an empty search is a legitimate answer
            out[key] = []
            out.setdefault("errors", []).append(f"{return_type}: {type(exc).__name__}")
    out["n_entries"] = len(out.get("entry_ids") or [])
    out["source_url"] = "https://search.rcsb.org/"
    out["retrieved_at"] = utcnow()
    return out


def register(registry, config):
    t = registry.tool
    t("pdb.entry", VERSION, license=LICENSE, default_tag="RETRIEVED", network=True,
      schema={"entry_id": "str"})(entry)
    t("pdb.download", VERSION, license=LICENSE, default_tag="RETRIEVED", network=True,
      schema={"entry_id": "str"})(download)
    t("pdb.ligands", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"pdb_path": "str"})(ligands)
    t("pdb.search_by_ligand_smiles", VERSION, license=LICENSE, default_tag="RETRIEVED",
      network=True, schema={"smiles": "str", "rows": "int"})(search_by_ligand_smiles)
    t("pdb.chemcomp", VERSION, license=LICENSE, default_tag="RETRIEVED", network=True,
      schema={"comp_id": "str"})(chemcomp)
    t("pdb.chain_sequences", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"pdb_path": "str"})(chain_sequences)
    t("pdb.extract_receptor", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"pdb_path": "str", "out_path": "str"})(extract_receptor)
    t("pdb.extract_ligand", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"pdb_path": "str", "resname": "str", "out_path": "str"})(extract_ligand)
    return registry
