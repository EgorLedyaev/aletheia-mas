"""ADMET-relevant properties.

Honesty note, stated in every output of this module: Aletheia bundles **no trained ADMET
model**. No ADMET toolkit with a verified licence and an offline build was available on this
host, so instead of shipping an unvalidated black box we compute (a) deterministic rule-based
developability filters and (b) two published literature equations, each flagged
`[UNVERIFIED-COEFFICIENTS]` because the source papers could not be opened from this
environment to check the constants.

  * `developability`  Lipinski / Veber / Egan / Ghose / lead-likeness rule panels -- COMPUTED
  * `esol_logS`       ESOL-style linear solubility estimate (Delaney-type) -- PREDICTED
  * `cns_mpo_like`    CNS-MPO-style desirability sum (Wager-type)            -- PREDICTED
  * `liability_alerts` structural liability SMARTS (hERG-like basic amine + lipophilic aromatic,
                       reactive/metabolic soft spots)                        -- COMPUTED

Anything emitted from the two literature equations carries
`note="uncertainty_unavailable: literature coefficients, not locally calibrated"` so the
provenance contract forces the caveat into the answer rather than leaving it to the writer.
"""
from __future__ import annotations

from typing import Any, Dict, List

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors

VERSION = "rule-based-1.0"
UNVERIFIED = "[UNVERIFIED-COEFFICIENTS] literature equation transcribed without source access"

LIABILITY_SMARTS: List[Dict[str, str]] = [
    {"name": "basic tertiary amine (hERG-type liability motif)", "smarts": "[NX3;H0;!$(N[!#6]);!$(N=*)]([CX4])([CX4])[CX4]"},
    {"name": "aniline N-dealkylation soft spot", "smarts": "[NX3;H1,H2][c]"},
    {"name": "para-hydroxylation-prone unsubstituted phenyl", "smarts": "[cH]1[cH][cH][cH][cH][c]1"},
    {"name": "O-dealkylation-prone alkyl aryl ether", "smarts": "[c][OX2][CH2,CH3]"},
    {"name": "thiophene/furan bioactivation motif", "smarts": "c1cc[s,o]c1"},
    {"name": "nitroaromatic reduction liability", "smarts": "[c][$([NX3](=O)=O),$([NX3+](=O)[O-])]"},
    {"name": "sulfonamide (PK/solubility handle, CA off-target)", "smarts": "[SX4](=O)(=O)[NX3]"},
    {"name": "carboxylic acid (permeability/glucuronidation)", "smarts": "[CX3](=O)[OX2H1]"},
]


def _mol(smiles: str) -> Chem.Mol:
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise ValueError(f"invalid SMILES: {smiles!r}")
    return m


def developability(smiles: str) -> Dict[str, Any]:
    """Deterministic developability rule panels (no model, pure arithmetic on descriptors)."""
    m = _mol(smiles)
    mw = Descriptors.MolWt(m)
    logp = Crippen.MolLogP(m)
    tpsa = rdMolDescriptors.CalcTPSA(m)
    hbd = rdMolDescriptors.CalcNumHBD(m)
    hba = rdMolDescriptors.CalcNumHBA(m)
    rotb = rdMolDescriptors.CalcNumRotatableBonds(m)
    nha = m.GetNumHeavyAtoms()
    mr = Crippen.MolMR(m)
    arom = rdMolDescriptors.CalcNumAromaticRings(m)
    panels = {
        "lipinski_ro5": {"pass": sum([mw > 500, logp > 5, hbd > 5, hba > 10]) <= 1,
                         "violations": sum([mw > 500, logp > 5, hbd > 5, hba > 10])},
        "veber": {"pass": rotb <= 10 and tpsa <= 140},
        "egan": {"pass": tpsa <= 131.6 and logp <= 5.88},
        "ghose": {"pass": (160 <= mw <= 480) and (-0.4 <= logp <= 5.6) and (20 <= nha <= 70)
                          and (40 <= mr <= 130)},
        "lead_like": {"pass": (200 <= mw <= 350) and (logp <= 3.5) and rotb <= 7},
        "ro3_fragment": {"pass": mw <= 300 and logp <= 3 and hbd <= 3 and hba <= 3 and rotb <= 3},
    }
    n_pass = sum(1 for p in panels.values() if p["pass"])
    return {"smiles": smiles, "descriptors": {"MolWt": round(mw, 2), "cLogP": round(logp, 3),
                                              "TPSA": round(tpsa, 2), "HBD": hbd, "HBA": hba,
                                              "RotB": rotb, "HeavyAtoms": nha,
                                              "AromaticRings": arom, "MolMR": round(mr, 2)},
            "panels": panels, "n_panels_passed": n_pass, "n_panels": len(panels),
            "method": "deterministic rule panels computed from RDKit descriptors"}


def esol_logS(smiles: str) -> Dict[str, Any]:
    """ESOL-style aqueous solubility estimate. Literature linear form; see module docstring."""
    m = _mol(smiles)
    logp = Crippen.MolLogP(m)
    mw = Descriptors.MolWt(m)
    rotb = rdMolDescriptors.CalcNumRotatableBonds(m)
    heavy = m.GetNumHeavyAtoms()
    arom_atoms = sum(1 for a in m.GetAtoms() if a.GetIsAromatic())
    ap = arom_atoms / heavy if heavy else 0.0
    log_s = 0.16 - 0.63 * logp - 0.0062 * mw + 0.066 * rotb - 0.74 * ap
    return {"smiles": smiles, "esol_logS": round(log_s, 3),
            "solubility_class": ("very soluble" if log_s > -1 else "soluble" if log_s > -2
                                 else "slightly soluble" if log_s > -4 else "poorly soluble"),
            "inputs": {"cLogP": round(logp, 3), "MolWt": round(mw, 2), "RotB": rotb,
                       "aromatic_proportion": round(ap, 3)},
            "model": "ESOL-type linear equation (Delaney-form)", "flag": UNVERIFIED,
            "units": "log10(mol/L)",
            "caveat": "ordering heuristic only; not calibrated on a local measured set"}


def cns_mpo_like(smiles: str) -> Dict[str, Any]:
    """CNS-MPO-style desirability sum over six physicochemical properties (0-6)."""
    m = _mol(smiles)
    logp = Crippen.MolLogP(m)
    tpsa = rdMolDescriptors.CalcTPSA(m)
    mw = Descriptors.MolWt(m)
    hbd = rdMolDescriptors.CalcNumHBD(m)
    logd = logp - 1.0          # crude logD7.4 proxy; no pKa model available
    pka = None

    def ramp(x: float, good: float, bad: float) -> float:
        if good == bad:
            return 1.0
        if (good < bad and x <= good) or (good > bad and x >= good):
            return 1.0
        if (good < bad and x >= bad) or (good > bad and x <= bad):
            return 0.0
        return round(abs((bad - x) / (bad - good)), 3)

    parts = {"cLogP": ramp(logp, 3.0, 5.0), "cLogD_proxy": ramp(logd, 2.0, 4.0),
             "MolWt": ramp(mw, 360.0, 500.0), "TPSA_upper": ramp(tpsa, 90.0, 120.0),
             "TPSA_lower": ramp(tpsa, 40.0, 20.0), "HBD": ramp(hbd, 0.5, 3.5)}
    score = round(sum(parts.values()), 3)
    return {"smiles": smiles, "cns_mpo_like": score, "max_score": 6.0, "components": parts,
            "model": "CNS-MPO-style desirability sum (Wager-form breakpoints)",
            "flag": UNVERIFIED,
            "caveat": "no pKa model on this host, so the logD term is a cLogP-1 proxy; "
                      "use for ordering CNS-likeness only"}


def liability_alerts(smiles: str) -> Dict[str, Any]:
    """Structural liability motifs relevant to ADME/tox triage (SMARTS matching, not a model)."""
    m = _mol(smiles)
    hits = []
    for pat in LIABILITY_SMARTS:
        q = Chem.MolFromSmarts(pat["smarts"])
        if q is not None and m.HasSubstructMatch(q):
            hits.append(pat["name"])
    logp = Crippen.MolLogP(m)
    basic_amine = any("hERG" in h for h in hits)
    return {"smiles": smiles, "n_alerts": len(hits), "alerts": hits,
            "herg_risk_flag": bool(basic_amine and logp > 3.0),
            "herg_flag_basis": "basic tertiary amine motif together with cLogP > 3 "
                               "(a coarse triage flag, not a hERG model)",
            "cLogP": round(logp, 3),
            "method": "SMARTS substructure alerts; no trained toxicity model is bundled"}


def profile(smiles: str) -> Dict[str, Any]:
    """Full ADMET-proxy profile for one molecule."""
    d = developability(smiles)
    s = esol_logS(smiles)
    c = cns_mpo_like(smiles)
    a = liability_alerts(smiles)
    return {"smiles": smiles, "developability": d, "solubility": s, "cns": c, "liabilities": a,
            "summary": {"n_panels_passed": d["n_panels_passed"], "esol_logS": s["esol_logS"],
                        "cns_mpo_like": c["cns_mpo_like"], "n_liability_alerts": a["n_alerts"],
                        "herg_risk_flag": a["herg_risk_flag"]},
            "disclaimer": "rule panels are COMPUTED; solubility and CNS scores are literature "
                          "equations with unverified constants and no local calibration"}


def register(registry, config):
    t = registry.tool
    lic = "BSD-3-Clause (RDKit descriptors); equations from published literature"
    t("admet.developability", VERSION, license=lic, default_tag="COMPUTED",
      schema={"smiles": "str"})(developability)
    t("admet.esol_logS", VERSION, license=lic, default_tag="PREDICTED",
      schema={"smiles": "str"})(esol_logS)
    t("admet.cns_mpo_like", VERSION, license=lic, default_tag="PREDICTED",
      schema={"smiles": "str"})(cns_mpo_like)
    t("admet.liability_alerts", VERSION, license=lic, default_tag="COMPUTED",
      schema={"smiles": "str"})(liability_alerts)
    t("admet.profile", VERSION, license=lic, default_tag="COMPUTED",
      schema={"smiles": "str"})(profile)
    return registry
