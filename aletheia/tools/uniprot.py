"""UniProtKB tools: accession lookup, gene-name search, PDB cross-references."""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from ..core.provenance import utcnow
from .http import get_json

BASE = "https://rest.uniprot.org/uniprotkb"
VERSION = "rest-2026"
LICENSE = "CC BY 4.0"

FIELDS = ("accession,id,protein_name,gene_names,organism_name,length,sequence,cc_function,"
          "ft_binding,ft_act_site,xref_pdb,cc_subcellular_location,protein_families,ec")


def entry(accession: str) -> Dict[str, Any]:
    """Full UniProtKB record for an accession, reduced to the fields the agents use."""
    d = get_json(f"{BASE}/{accession}.json")
    seq = (d.get("sequence") or {}).get("value")
    genes = [g.get("geneName", {}).get("value") for g in d.get("genes", []) if g.get("geneName")]
    prot = (((d.get("proteinDescription") or {}).get("recommendedName") or {})
            .get("fullName", {}) or {}).get("value")
    pdbs, pdb_meta = [], []
    for x in d.get("uniProtKBCrossReferences", []):
        if x.get("database") == "PDB":
            pdbs.append(x["id"])
            props = {p["key"]: p["value"] for p in x.get("properties", [])}
            pdb_meta.append({"pdb_id": x["id"], "method": props.get("Method"),
                             "resolution": props.get("Resolution"), "chains": props.get("Chains")})
    functions = [t.get("value") for c in d.get("comments", []) if c.get("commentType") == "FUNCTION"
                 for t in c.get("texts", [])]
    binding = []
    for f in d.get("features", []):
        if f.get("type") in ("Binding site", "Active site"):
            loc = f.get("location", {})
            binding.append({"type": f.get("type"),
                            "start": (loc.get("start") or {}).get("value"),
                            "end": (loc.get("end") or {}).get("value"),
                            "ligand": (f.get("ligand") or {}).get("name"),
                            "description": f.get("description")})
    return {"accession": d.get("primaryAccession"), "uniprot_id": d.get("uniProtkbId"),
            "protein_name": prot, "genes": genes,
            "organism": (d.get("organism") or {}).get("scientificName"),
            "taxon_id": (d.get("organism") or {}).get("taxonId"),
            "length": (d.get("sequence") or {}).get("length"),
            "sequence": seq,
            "sequence_md5": hashlib.md5((seq or "").encode()).hexdigest() if seq else None,
            "sequence_crc64": (d.get("sequence") or {}).get("crc64"),
            "function": functions[:2], "binding_features": binding[:25],
            "pdb_ids": pdbs, "pdb_entries": pdb_meta,
            "ec_numbers": [e.get("value") for e in
                           ((d.get("proteinDescription") or {}).get("recommendedName") or {})
                           .get("ecNumbers", [])],
            "entry_version": d.get("entryAudit", {}).get("entryVersion"),
            "last_modified": d.get("entryAudit", {}).get("lastAnnotationUpdateDate"),
            "retrieved_at": utcnow(), "source_url": f"https://www.uniprot.org/uniprotkb/{accession}"}


def search_gene(gene: str, organism_id: int = 9606, reviewed: bool = True,
                limit: int = 5) -> Dict[str, Any]:
    """Resolve a gene symbol to reviewed UniProt accessions (human by default)."""
    q = f"gene:{gene} AND organism_id:{organism_id}" + (" AND reviewed:true" if reviewed else "")
    d = get_json(f"{BASE}/search", {"query": q, "fields": "accession,id,protein_name,gene_names,length",
                                    "size": limit, "format": "json"})
    hits = []
    for r in d.get("results", []):
        prot = (((r.get("proteinDescription") or {}).get("recommendedName") or {})
                .get("fullName", {}) or {}).get("value")
        hits.append({"accession": r.get("primaryAccession"), "uniprot_id": r.get("uniProtkbId"),
                     "protein_name": prot, "length": (r.get("sequence") or {}).get("length"),
                     "genes": [g.get("geneName", {}).get("value") for g in r.get("genes", [])]})
    return {"query": q, "hits": hits, "n_hits": len(hits), "retrieved_at": utcnow(),
            "source_url": f"https://rest.uniprot.org/uniprotkb/search?query={q}"}


def sequence_features(sequence: str) -> Dict[str, Any]:
    """Composition features computed locally from a sequence (no network)."""
    from collections import Counter
    seq = (sequence or "").upper()
    if not seq:
        raise ValueError("empty sequence")
    c = Counter(seq)
    n = len(seq)
    groups = {"hydrophobic": "AVILMFWC", "polar": "STNQY", "positive": "KRH",
              "negative": "DE", "special": "GP"}
    comp = {k: round(sum(c[a] for a in v) / n, 4) for k, v in groups.items()}
    kd = {"A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "Q": -3.5, "E": -3.5, "G": -0.4,
          "H": -3.2, "I": 4.5, "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6, "S": -0.8,
          "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2}
    gravy = round(sum(kd.get(a, 0.0) for a in seq) / n, 4)
    mw = round(sum({"A": 71.08, "R": 156.19, "N": 114.10, "D": 115.09, "C": 103.14, "Q": 128.13,
                    "E": 129.12, "G": 57.05, "H": 137.14, "I": 113.16, "L": 113.16, "K": 128.17,
                    "M": 131.19, "F": 147.18, "P": 97.12, "S": 87.08, "T": 101.10, "W": 186.21,
                    "Y": 163.18, "V": 99.13}.get(a, 110.0) for a in seq) + 18.02, 1)
    return {"length": n, "composition": comp, "gravy": gravy, "mw_da": mw,
            "net_charge_ph7": c["K"] + c["R"] - c["D"] - c["E"],
            "cys_count": c["C"], "most_common": c.most_common(5)}


def register(registry, config):
    t = registry.tool
    t("uniprot.entry", VERSION, license=LICENSE, default_tag="RETRIEVED", network=True,
      schema={"accession": "str"})(entry)
    t("uniprot.search_gene", VERSION, license=LICENSE, default_tag="RETRIEVED", network=True,
      schema={"gene": "str", "organism_id": "int"})(search_gene)
    t("uniprot.sequence_features", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"sequence": "str"})(sequence_features)
    return registry
