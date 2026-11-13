"""AlphaFold DB tools: model retrieval and pLDDT confidence summary computed from the file."""
from __future__ import annotations

import hashlib
import os
import statistics
from typing import Any, Dict, List

from ..core.provenance import utcnow
from .http import get_json, get_text

API = "https://alphafold.ebi.ac.uk/api/prediction"
VERSION = "afdb-api"
LICENSE = "CC BY 4.0"


def prediction(accession: str) -> Dict[str, Any]:
    """AlphaFold DB entry metadata for a UniProt accession."""
    d = get_json(f"{API}/{accession}")
    if not d:
        raise FileNotFoundError(f"no AlphaFold model for {accession}")
    e = d[0]
    return {"accession": accession, "entry_id": e.get("entryId"),
            "model_version": e.get("latestVersion"), "model_created": e.get("modelCreatedDate"),
            "uniprot_start": e.get("uniprotStart"), "uniprot_end": e.get("uniprotEnd"),
            "sequence": e.get("uniprotSequence"),
            "pdb_url": e.get("pdbUrl"), "cif_url": e.get("cifUrl"),
            "global_metric_value": e.get("globalMetricValue"),
            "retrieved_at": utcnow(),
            "source_url": f"https://alphafold.ebi.ac.uk/entry/{accession}"}


def download_model(accession: str, dest_dir: str = "cache/structures") -> Dict[str, Any]:
    """Download the AlphaFold PDB model."""
    meta = prediction(accession)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"AF-{accession}.pdb")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(get_text(meta["pdb_url"]))
    raw = open(path, "rb").read()
    return {"accession": accession, "path": path.replace("\\", "/"),
            "entry_id": meta["entry_id"], "model_version": meta["model_version"],
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "retrieved_at": utcnow(), "source_url": meta["pdb_url"]}


def plddt_summary(pdb_path: str) -> Dict[str, Any]:
    """Per-residue pLDDT (B-factor column of CA atoms) summarised into confidence bands."""
    vals: List[float] = []
    for ln in open(pdb_path, "r", encoding="utf-8", errors="ignore"):
        if ln.startswith("ATOM") and ln[12:16].strip() == "CA":
            try:
                vals.append(float(ln[60:66]))
            except ValueError:
                continue
    if not vals:
        raise ValueError(f"no CA B-factors in {pdb_path}")
    n = len(vals)
    return {"n_residues": n, "mean_plddt": round(statistics.fmean(vals), 2),
            "median_plddt": round(statistics.median(vals), 2),
            "min_plddt": round(min(vals), 2), "max_plddt": round(max(vals), 2),
            "frac_very_high_gt90": round(sum(v > 90 for v in vals) / n, 4),
            "frac_confident_70_90": round(sum(70 <= v <= 90 for v in vals) / n, 4),
            "frac_low_lt70": round(sum(v < 70 for v in vals) / n, 4),
            "interpretation": "pLDDT is a per-residue model-confidence score, not an accuracy guarantee"}


def register(registry, config):
    t = registry.tool
    t("alphafold.prediction", VERSION, license=LICENSE, default_tag="RETRIEVED", network=True,
      schema={"accession": "str"})(prediction)
    t("alphafold.download_model", VERSION, license=LICENSE, default_tag="RETRIEVED", network=True,
      schema={"accession": "str"})(download_model)
    t("alphafold.plddt_summary", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"pdb_path": "str"})(plddt_summary)
    return registry
