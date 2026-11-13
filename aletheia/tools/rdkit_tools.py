"""RDKit tools: standardisation, descriptors, drug-likeness, structural alerts, similarity.

Everything here is deterministic arithmetic on a molecular graph -> emitted as COMPUTED.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

import rdkit
from rdkit import Chem, DataStructs, RDConfig, RDLogger
from rdkit.Chem import AllChem, Crippen, Descriptors, FilterCatalog, QED, rdMolDescriptors
from rdkit.Chem.FilterCatalog import FilterCatalogParams
from rdkit.Chem.Scaffolds import MurckoScaffold

RDLogger.DisableLog("rdApp.*")
VERSION = rdkit.__version__

sys.path.append(os.path.join(RDConfig.RDContribDir, "SA_Score"))
try:
    import sascorer  # type: ignore
    _HAVE_SA = True
except Exception:                                    # pragma: no cover
    _HAVE_SA = False

_CATALOGS: Dict[str, FilterCatalog.FilterCatalog] = {}


def _catalog(name: str) -> FilterCatalog.FilterCatalog:
    if name not in _CATALOGS:
        p = FilterCatalogParams()
        p.AddCatalog(getattr(FilterCatalogParams.FilterCatalogs, name))
        _CATALOGS[name] = FilterCatalog.FilterCatalog(p)
    return _CATALOGS[name]


def parse(smiles: str) -> Chem.Mol:
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise ValueError(f"invalid SMILES: {smiles!r}")
    return m


def standardize(smiles: str) -> Dict[str, Any]:
    """Canonical SMILES, largest fragment, InChIKey, formula."""
    m = parse(smiles)
    frags = Chem.GetMolFrags(m, asMols=True, sanitizeFrags=True)
    if len(frags) > 1:
        m = max(frags, key=lambda f: f.GetNumHeavyAtoms())
    Chem.SanitizeMol(m)
    return {"canonical_smiles": Chem.MolToSmiles(m),
            "inchikey": Chem.inchi.MolToInchiKey(m),
            "formula": rdMolDescriptors.CalcMolFormula(m),
            "n_fragments": len(frags),
            "heavy_atoms": m.GetNumHeavyAtoms(),
            "input_smiles": smiles}


DESCRIPTOR_KEYS = ["MolWt", "cLogP", "TPSA", "HBD", "HBA", "RotB", "RingCount",
                   "AromaticRings", "HeavyAtoms", "FractionCSP3", "FormalCharge",
                   "QED", "SAscore", "MolMR", "NumStereocentres"]


def descriptors(smiles: str) -> Dict[str, Any]:
    """Physico-chemical descriptors + QED + synthetic accessibility."""
    m = parse(smiles)
    d: Dict[str, Any] = {
        "MolWt": round(Descriptors.MolWt(m), 3),
        "cLogP": round(Crippen.MolLogP(m), 3),
        "TPSA": round(rdMolDescriptors.CalcTPSA(m), 2),
        "HBD": rdMolDescriptors.CalcNumHBD(m),
        "HBA": rdMolDescriptors.CalcNumHBA(m),
        "RotB": rdMolDescriptors.CalcNumRotatableBonds(m),
        "RingCount": rdMolDescriptors.CalcNumRings(m),
        "AromaticRings": rdMolDescriptors.CalcNumAromaticRings(m),
        "HeavyAtoms": m.GetNumHeavyAtoms(),
        "FractionCSP3": round(rdMolDescriptors.CalcFractionCSP3(m), 3),
        "FormalCharge": Chem.GetFormalCharge(m),
        "MolMR": round(Crippen.MolMR(m), 3),
        "NumStereocentres": len(Chem.FindMolChiralCenters(m, includeUnassigned=True,
                                                          useLegacyImplementation=False)),
        "QED": round(QED.qed(m), 4),
    }
    d["SAscore"] = round(sascorer.calculateScore(m), 3) if _HAVE_SA else None
    return d


def druglikeness(smiles: str) -> Dict[str, Any]:
    """Lipinski Ro5 and Veber rules, evaluated from RDKit descriptors."""
    d = descriptors(smiles)
    ro5 = {"MolWt<=500": d["MolWt"] <= 500, "cLogP<=5": d["cLogP"] <= 5,
           "HBD<=5": d["HBD"] <= 5, "HBA<=10": d["HBA"] <= 10}
    veber = {"RotB<=10": d["RotB"] <= 10, "TPSA<=140": d["TPSA"] <= 140}
    n_viol = sum(1 for v in ro5.values() if not v)
    return {"lipinski": ro5, "lipinski_violations": n_viol, "lipinski_pass": n_viol <= 1,
            "veber": veber, "veber_pass": all(veber.values()),
            "qed": d["QED"], "sa_score": d["SAscore"], "descriptors": d}


def alerts(smiles: str, catalogs: Optional[List[str]] = None) -> Dict[str, Any]:
    """Structural alerts from RDKit's bundled filter catalogs (PAINS / Brenk / NIH / ChEMBL)."""
    catalogs = catalogs or ["PAINS", "BRENK", "NIH"]
    m = parse(smiles)
    hits: Dict[str, List[str]] = {}
    for name in catalogs:
        cat = _catalog(name)
        ms = cat.GetMatches(m)
        hits[name] = sorted({e.GetDescription() for e in ms})
    total = sum(len(v) for v in hits.values())
    return {"alerts": hits, "n_alerts": total, "clean": total == 0,
            "catalogs_used": catalogs,
            "catalog_sizes": {n: _catalog(n).GetNumEntries() for n in catalogs}}


def scaffold(smiles: str) -> Dict[str, Any]:
    """Bemis-Murcko scaffold (used for leakage-free splitting and diversity)."""
    m = parse(smiles)
    sc = MurckoScaffold.GetScaffoldForMol(m)
    generic = MurckoScaffold.MakeScaffoldGeneric(sc) if sc.GetNumAtoms() else sc
    return {"murcko_smiles": Chem.MolToSmiles(sc),
            "generic_scaffold": Chem.MolToSmiles(generic),
            "n_scaffold_atoms": sc.GetNumAtoms()}


def fingerprint(smiles: str, radius: int = 2, n_bits: int = 2048):
    m = parse(smiles)
    gen = AllChem.GetMorganGenerator(radius=radius, fpSize=n_bits)
    return gen.GetFingerprint(m)


def similarity(smiles_a: str, smiles_b: str, radius: int = 2, n_bits: int = 2048) -> Dict[str, Any]:
    """Tanimoto similarity on Morgan fingerprints."""
    fa, fb = fingerprint(smiles_a, radius, n_bits), fingerprint(smiles_b, radius, n_bits)
    return {"tanimoto": round(DataStructs.TanimotoSimilarity(fa, fb), 4),
            "fp": f"Morgan r={radius} bits={n_bits}"}


def similarity_matrix(smiles_list: List[str], radius: int = 2, n_bits: int = 2048) -> Dict[str, Any]:
    """Pairwise Tanimoto matrix; used by diversity selection and applicability domain."""
    fps = [fingerprint(s, radius, n_bits) for s in smiles_list]
    mat = []
    for i, f in enumerate(fps):
        sims = DataStructs.BulkTanimotoSimilarity(f, fps)
        mat.append([round(float(x), 4) for x in sims])
    import statistics
    off = [mat[i][j] for i in range(len(fps)) for j in range(i + 1, len(fps))]
    return {"matrix": mat, "n": len(fps),
            "mean_pairwise_similarity": round(statistics.fmean(off), 4) if off else None,
            "max_pairwise_similarity": round(max(off), 4) if off else None}


def validate_batch(smiles_list: List[str]) -> Dict[str, Any]:
    """Validity / uniqueness report for a generated batch."""
    ok, bad, canon = [], [], []
    for s in smiles_list:
        m = Chem.MolFromSmiles(s)
        if m is None:
            bad.append(s)
        else:
            ok.append(s)
            canon.append(Chem.MolToSmiles(m))
    uniq = sorted(set(canon))
    return {"n_input": len(smiles_list), "n_valid": len(ok), "n_invalid": len(bad),
            "validity": round(len(ok) / len(smiles_list), 4) if smiles_list else 0.0,
            "n_unique": len(uniq),
            "uniqueness": round(len(uniq) / len(ok), 4) if ok else 0.0,
            "invalid_examples": bad[:5], "canonical": canon, "unique_smiles": uniq}


def register(registry, config):
    t = registry.tool
    t("rdkit.standardize", VERSION, license="BSD-3-Clause", default_tag="COMPUTED",
      schema={"smiles": "str"})(standardize)
    t("rdkit.descriptors", VERSION, license="BSD-3-Clause", default_tag="COMPUTED",
      schema={"smiles": "str"})(descriptors)
    t("rdkit.druglikeness", VERSION, license="BSD-3-Clause", default_tag="COMPUTED",
      schema={"smiles": "str"})(druglikeness)
    t("rdkit.alerts", VERSION, license="BSD-3-Clause", default_tag="COMPUTED",
      schema={"smiles": "str", "catalogs": "list[str]"})(alerts)
    t("rdkit.scaffold", VERSION, license="BSD-3-Clause", default_tag="COMPUTED",
      schema={"smiles": "str"})(scaffold)
    t("rdkit.similarity", VERSION, license="BSD-3-Clause", default_tag="COMPUTED",
      schema={"smiles_a": "str", "smiles_b": "str"})(similarity)
    t("rdkit.similarity_matrix", VERSION, license="BSD-3-Clause", default_tag="COMPUTED",
      schema={"smiles_list": "list[str]"})(similarity_matrix)
    t("rdkit.validate_batch", VERSION, license="BSD-3-Clause", default_tag="COMPUTED",
      schema={"smiles_list": "list[str]"})(validate_batch)
    return registry
