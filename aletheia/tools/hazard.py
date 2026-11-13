"""Structural hazard screening for generated or submitted molecules.

Purpose is *defensive triage only*: flag structures that must not be progressed by an
automated design loop, and give the Safety agent a machine-readable reason. The patterns are
deliberately coarse scaffold-level SMARTS -- they are screening filters, not identification
tools, and this module contains no synthesis, route or precursor information of any kind.

Three severities:
  BLOCK   motifs characteristic of chemical-weapon classes -> design/optimisation is refused
  REVIEW  scaffolds characteristic of internationally controlled substance classes -> refused
          for optimisation, allowed for read-only property questions with a logged note
  NOTE    classical toxicophores / reactive groups -> reported, candidate penalised, not refused
"""
from __future__ import annotations

from typing import Any, Dict, List

from rdkit import Chem

BLOCK_PATTERNS: List[Dict[str, str]] = [
    {"name": "phosphonofluoridate-like P-F", "smarts": "[P](=O)(F)", "class": "CW nerve-agent class"},
    {"name": "phosphoramidocyanidate-like P-CN", "smarts": "[P](=O)C#N", "class": "CW nerve-agent class"},
    {"name": "phosphonothiolate aminoethyl", "smarts": "[P](=O)SCCN", "class": "CW V-series class"},
    {"name": "bis(2-chloroethyl) sulfide motif", "smarts": "S(CCCl)CCCl", "class": "CW vesicant class"},
    {"name": "bis(2-chloroethyl) amine motif", "smarts": "N(CCCl)CCCl", "class": "CW vesicant class"},
    {"name": "organoarsenic chloride", "smarts": "[As]Cl", "class": "CW vesicant class"},
    {"name": "phosgene-like acyl dichloride", "smarts": "O=C(Cl)Cl", "class": "CW choking-agent class"},
    {"name": "perfluoroisobutylene-like", "smarts": "FC(F)=C(C(F)(F)F)C(F)(F)F", "class": "CW choking-agent class"},
]

REVIEW_PATTERNS: List[Dict[str, str]] = [
    {"name": "4-anilidopiperidine core", "smarts": "O=C(N(c1ccccc1)C1CCNCC1)", "class": "controlled opioid class"},
    {"name": "morphinan core", "smarts": "C1CC2CCC3C(C2)Oc2ccccc2C13", "class": "controlled opioid class"},
    {"name": "amphetamine-like phenylisopropylamine", "smarts": "c1ccccc1CC(C)[NX3;H2,H1,H0]", "class": "controlled stimulant class"},
    {"name": "cathinone-like aryl ketone amine", "smarts": "c1ccccc1C(=O)C(C)[NX3]", "class": "controlled stimulant class"},
    {"name": "tryptamine core", "smarts": "c1cc2[nH]cc(CC[NX3])c2cc1", "class": "controlled hallucinogen class"},
    {"name": "lysergamide core", "smarts": "C1=CC2=C3C(=C1)NC=C3CC1N(C)CC(C(=O)N)CC21", "class": "controlled hallucinogen class"},
    {"name": "1-aryl-cyclohexylamine (PCP-like)", "smarts": "C1(c2ccccc2)(CCCCC1)[NX3]", "class": "controlled dissociative class"},
    {"name": "1,4-benzodiazepin-2-one core", "smarts": "O=C1CN=C(c2ccccc2)c2ccccc2N1", "class": "controlled depressant class"},
    {"name": "dibenzopyran cannabinoid core", "smarts": "CC1(C)Oc2cc(O)ccc2C2CCCCC12", "class": "controlled cannabinoid class"},
]

NOTE_PATTERNS: List[Dict[str, str]] = [
    {"name": "aromatic nitro", "smarts": "[$([NX3](=O)=O),$([NX3+](=O)[O-])][c]", "class": "toxicophore"},
    {"name": "aromatic amine", "smarts": "[NX3;H2][c]", "class": "toxicophore"},
    {"name": "nitrosamine", "smarts": "[NX3][NX2]=O", "class": "toxicophore"},
    {"name": "hydrazine", "smarts": "[NX3][NX3]", "class": "toxicophore"},
    {"name": "azo", "smarts": "[c][NX2]=[NX2][c]", "class": "toxicophore"},
    {"name": "epoxide", "smarts": "C1OC1", "class": "reactive"},
    {"name": "aziridine", "smarts": "C1NC1", "class": "reactive"},
    {"name": "acyl halide", "smarts": "C(=O)[F,Cl,Br,I]", "class": "reactive"},
    {"name": "isocyanate/isothiocyanate", "smarts": "N=C=[O,S]", "class": "reactive"},
    {"name": "Michael acceptor", "smarts": "C=CC(=O)[!O]", "class": "reactive"},
    {"name": "aldehyde", "smarts": "[CX3H1](=O)[#6]", "class": "reactive"},
    {"name": "quinone", "smarts": "O=C1C=CC(=O)C=C1", "class": "toxicophore"},
    {"name": "thiourea", "smarts": "[NX3]C(=S)[NX3]", "class": "toxicophore"},
    {"name": "organic azide", "smarts": "[NX2]=[NX2+]=[NX1-]", "class": "energetic"},
    {"name": "peroxide", "smarts": "[OX2][OX2]", "class": "energetic"},
    {"name": "polynitro aromatic", "smarts": "c1([$([NX3](=O)=O),$([NX3+](=O)[O-])])c([$([NX3](=O)=O),$([NX3+](=O)[O-])])cccc1", "class": "energetic"},
]

_COMPILED: Dict[str, Any] = {}


def _compile():
    if _COMPILED:
        return _COMPILED
    for sev, pats in (("BLOCK", BLOCK_PATTERNS), ("REVIEW", REVIEW_PATTERNS), ("NOTE", NOTE_PATTERNS)):
        rows = []
        for p in pats:
            q = Chem.MolFromSmarts(p["smarts"])
            if q is not None:
                rows.append({**p, "query": q})
        _COMPILED[sev] = rows
    return _COMPILED


def screen(smiles: str) -> Dict[str, Any]:
    """Screen one structure; returns severity, matched motif names and the decision."""
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise ValueError(f"invalid SMILES: {smiles!r}")
    cat = _compile()
    hits = {"BLOCK": [], "REVIEW": [], "NOTE": []}
    for sev, rows in cat.items():
        for p in rows:
            if m.HasSubstructMatch(p["query"]):
                hits[sev].append({"motif": p["name"], "class": p["class"]})
    severity = "BLOCK" if hits["BLOCK"] else ("REVIEW" if hits["REVIEW"] else
                                              ("NOTE" if hits["NOTE"] else "CLEAR"))
    return {"smiles": smiles, "severity": severity, "hits": hits,
            "n_block": len(hits["BLOCK"]), "n_review": len(hits["REVIEW"]),
            "n_note": len(hits["NOTE"]),
            "patterns_version": "aletheia-hazard-1.0",
            "n_patterns_screened": sum(len(v) for v in cat.values()),
            "decision": {"BLOCK": "refuse: chemical-weapon-class motif",
                         "REVIEW": "refuse optimisation: controlled-substance-class scaffold",
                         "NOTE": "allow with recorded structural alert",
                         "CLEAR": "allow"}[severity]}


def screen_batch(smiles_list: List[str]) -> Dict[str, Any]:
    """Screen a batch; used as a gate on every generated candidate set."""
    rows, errors = [], []
    for s in smiles_list:
        try:
            rows.append(screen(s))
        except ValueError as exc:
            errors.append({"smiles": s, "error": str(exc)})
    return {"n_screened": len(rows),
            "n_block": sum(r["severity"] == "BLOCK" for r in rows),
            "n_review": sum(r["severity"] == "REVIEW" for r in rows),
            "n_note": sum(r["severity"] == "NOTE" for r in rows),
            "n_clear": sum(r["severity"] == "CLEAR" for r in rows),
            "blocked_smiles": [r["smiles"] for r in rows if r["severity"] in ("BLOCK", "REVIEW")],
            "results": rows, "errors": errors,
            "patterns_version": "aletheia-hazard-1.0"}


def register(registry, config):
    t = registry.tool
    t("hazard.screen", "1.0", license="BSD-3-Clause (RDKit SMARTS)", default_tag="COMPUTED",
      schema={"smiles": "str"})(screen)
    t("hazard.screen_batch", "1.0", license="BSD-3-Clause (RDKit SMARTS)", default_tag="COMPUTED",
      schema={"smiles_list": "list[str]"})(screen_batch)
    return registry
