"""Molecule generators -- four mechanistically independent samplers.

Independence matters: a single generator plus a single scoring oracle is the classic recipe for
Goodhart failure, where the batch drifts into whatever the oracle over-rewards. Aletheia runs
several samplers whose failure modes are unrelated and reports per-generator statistics.

  G1 rule_decorate    reaction-SMARTS decoration + bioisosteric replacement of a seed
  G2 brics_recombine  BRICS fragmentation of retrieved actives, recombined (data-driven)
  G3 selfies_mutate   random SELFIES token mutation (validity by construction)
  G4 llm_edits        LLM-proposed medicinal-chemistry edits, validated by RDKit (agent-side)

None of these is a pretrained deep generative model: no deep generator with a verified offline
CPU build was available on this host, and the project refuses to claim one it did not run.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem, BRICS

RDLogger.DisableLog("rdApp.*")
VERSION = "1.0"

# Reaction SMARTS for common, synthetically plausible decorations.
DECORATIONS: List[Dict[str, str]] = [
    {"name": "aromatic H -> F", "smarts": "[cH:1]>>[c:1]F"},
    {"name": "aromatic H -> Cl", "smarts": "[cH:1]>>[c:1]Cl"},
    {"name": "aromatic H -> methyl", "smarts": "[cH:1]>>[c:1]C"},
    {"name": "aromatic H -> methoxy", "smarts": "[cH:1]>>[c:1]OC"},
    {"name": "aromatic H -> hydroxyl", "smarts": "[cH:1]>>[c:1]O"},
    {"name": "aromatic H -> CF3", "smarts": "[cH:1]>>[c:1]C(F)(F)F"},
    {"name": "aromatic H -> nitrile", "smarts": "[cH:1]>>[c:1]C#N"},
    {"name": "aromatic H -> morpholinoethoxy", "smarts": "[cH:1]>>[c:1]OCCN1CCOCC1"},
    {"name": "aromatic H -> N-methylpiperazinyl", "smarts": "[cH:1]>>[c:1]N1CCN(C)CC1"},
    {"name": "aromatic H -> sulfonamide", "smarts": "[cH:1]>>[c:1]S(N)(=O)=O"},
    {"name": "aromatic H -> carboxamide", "smarts": "[cH:1]>>[c:1]C(N)=O"},
    {"name": "methyl -> ethyl", "smarts": "[cH0:1][CH3:2]>>[c:1][CH2:2]C"},
    {"name": "methoxy -> ethoxy", "smarts": "[c:1][OX2][CH3:2]>>[c:1]O[CH2:2]C"},
]

# Bioisosteric replacements (classic medicinal-chemistry swaps).
BIOISOSTERES: List[Dict[str, str]] = [
    {"name": "carboxylic acid -> tetrazole", "smarts": "[CX3](=O)[OX2H1]>>c1nn[nH]n1"},
    {"name": "carboxylic acid -> acylsulfonamide", "smarts": "[CX3](=O)[OX2H1]>>C(=O)NS(C)(=O)=O"},
    {"name": "amide -> 1,2,4-oxadiazole", "smarts": "[CX3](=O)[NX3H1]>>c1nc(no1)"},
    {"name": "phenyl -> pyridyl", "smarts": "[cH:1]1[cH:2][cH:3][cH:4][cH:5][cH:6]1>>"
                                            "[n:1]1[cH:2][cH:3][cH:4][cH:5][cH:6]1"},
    {"name": "ester -> amide", "smarts": "[CX3:1](=O)[OX2][CH3]>>[C:1](=O)NC"},
    {"name": "ketone -> oxime ether", "smarts": "[CX3:1](=O)[#6:2]>>[C:1](=NOC)[#6:2]"},
    {"name": "methyl ether -> difluoromethyl ether", "smarts": "[OX2:1][CH3]>>[O:1]C(F)F"},
    {"name": "terminal alkyne -> nitrile", "smarts": "[CH1:1]#[CX2:2]>>[N:1]#[C:2]"},
]


def _canon(m: Chem.Mol) -> Optional[str]:
    try:
        Chem.SanitizeMol(m)
        smi = Chem.MolToSmiles(m)
        return smi if Chem.MolFromSmiles(smi) else None
    except Exception:
        return None


def rule_decorate(seed_smiles: str, n: int = 40, seed: int = 42,
                  max_per_rule: int = 3) -> Dict[str, Any]:
    """G1: apply reaction-SMARTS decorations and bioisosteric swaps to a seed molecule."""
    rng = random.Random(seed)
    m = Chem.MolFromSmiles(seed_smiles)
    if m is None:
        raise ValueError(f"invalid seed SMILES: {seed_smiles!r}")
    out: Dict[str, Dict[str, Any]] = {}
    rules = DECORATIONS + BIOISOSTERES
    rng.shuffle(rules)
    for rule in rules:
        try:
            rxn = AllChem.ReactionFromSmarts(rule["smarts"])
            prods = rxn.RunReactants((m,))
        except Exception:
            continue
        kept = 0
        for tup in prods:
            smi = _canon(tup[0])
            if smi and smi != Chem.MolToSmiles(m) and smi not in out:
                out[smi] = {"smiles": smi, "transform": rule["name"], "generator": "G1_rule_decorate",
                            "parent": Chem.MolToSmiles(m)}
                kept += 1
            if kept >= max_per_rule or len(out) >= n:
                break
        if len(out) >= n:
            break
    return {"generator": "G1_rule_decorate", "n_generated": len(out),
            "molecules": list(out.values()), "seed": seed,
            "n_rules": len(rules), "params": {"max_per_rule": max_per_rule}}


def brics_recombine(smiles_list: List[str], n: int = 40, seed: int = 42,
                    min_heavy: int = 14, max_heavy: int = 45) -> Dict[str, Any]:
    """G2: BRICS-fragment the supplied actives and recombine fragments into new structures."""
    rng = random.Random(seed)
    mols = [Chem.MolFromSmiles(s) for s in smiles_list]
    mols = [m for m in mols if m is not None]
    if not mols:
        raise ValueError("no valid input molecules for BRICS recombination")
    frags = set()
    for m in mols[:120]:
        frags |= set(BRICS.BRICSDecompose(m, returnMols=False))
    frag_mols = [Chem.MolFromSmiles(f) for f in frags]
    frag_mols = [f for f in frag_mols if f is not None]
    if len(frag_mols) < 2:
        raise ValueError("BRICS decomposition produced too few fragments")
    built, seen = [], set(Chem.MolToSmiles(m) for m in mols)
    gen = BRICS.BRICSBuild(frag_mols, scrambleReagents=True, seeds=None, maxDepth=3)
    for i, prod in enumerate(gen):
        if len(built) >= n or i > n * 60:
            break
        try:
            prod.UpdatePropertyCache(strict=False)
            smi = _canon(prod)
        except Exception:
            continue
        if not smi or smi in seen:
            continue
        nh = Chem.MolFromSmiles(smi).GetNumHeavyAtoms()
        if not (min_heavy <= nh <= max_heavy):
            continue
        seen.add(smi)
        built.append({"smiles": smi, "transform": "BRICS recombination",
                      "generator": "G2_brics_recombine", "parent": None})
    return {"generator": "G2_brics_recombine", "n_generated": len(built),
            "molecules": built, "n_fragments": len(frag_mols), "n_inputs": len(mols),
            "seed": seed, "params": {"min_heavy": min_heavy, "max_heavy": max_heavy}}


def selfies_mutate(seed_smiles: str, n: int = 40, seed: int = 42,
                   n_mutations: int = 2) -> Dict[str, Any]:
    """G3: random SELFIES token mutations -- every string decodes to a valid molecule."""
    try:
        import selfies as sf
    except ImportError as exc:
        raise RuntimeError(f"selfies package not installed: {exc}")
    rng = random.Random(seed)
    m = Chem.MolFromSmiles(seed_smiles)
    if m is None:
        raise ValueError(f"invalid seed SMILES: {seed_smiles!r}")
    base = sf.encoder(Chem.MolToSmiles(m))
    alphabet = sorted(sf.get_semantic_robust_alphabet())
    out: Dict[str, Dict[str, Any]] = {}
    tries = 0
    while len(out) < n and tries < n * 40:
        tries += 1
        toks = list(sf.split_selfies(base))
        for _ in range(rng.randint(1, n_mutations)):
            op = rng.choice(["replace", "insert", "delete"])
            if op == "delete" and len(toks) > 4:
                toks.pop(rng.randrange(len(toks)))
            elif op == "insert":
                toks.insert(rng.randrange(len(toks) + 1), rng.choice(alphabet))
            else:
                toks[rng.randrange(len(toks))] = rng.choice(alphabet)
        try:
            smi = sf.decoder("".join(toks))
        except Exception:
            continue
        mm = Chem.MolFromSmiles(smi) if smi else None
        if mm is None or mm.GetNumHeavyAtoms() < 10:
            continue
        can = Chem.MolToSmiles(mm)
        if can and can != Chem.MolToSmiles(m) and can not in out:
            out[can] = {"smiles": can, "transform": "SELFIES token mutation",
                        "generator": "G3_selfies_mutate", "parent": Chem.MolToSmiles(m)}
    return {"generator": "G3_selfies_mutate", "n_generated": len(out),
            "molecules": list(out.values()), "seed": seed, "n_attempts": tries,
            "alphabet_size": len(alphabet), "params": {"n_mutations": n_mutations}}


def validate_proposals(proposals: List[Dict[str, Any]], seed_smiles: Optional[str] = None,
                       generator: str = "G4_llm_edits") -> Dict[str, Any]:
    """G4 validator: keep only LLM proposals that RDKit can parse; report what was discarded."""
    kept, rejected = [], []
    seen = set()
    parent = Chem.MolToSmiles(Chem.MolFromSmiles(seed_smiles)) if seed_smiles and \
        Chem.MolFromSmiles(seed_smiles) else None
    for p in proposals or []:
        smi = (p.get("smiles") or "").strip()
        m = Chem.MolFromSmiles(smi) if smi else None
        if m is None:
            rejected.append({"smiles": smi, "reason": "unparseable SMILES"})
            continue
        can = Chem.MolToSmiles(m)
        if can in seen or can == parent:
            rejected.append({"smiles": can, "reason": "duplicate of parent or earlier proposal"})
            continue
        seen.add(can)
        kept.append({"smiles": can, "transform": (p.get("rationale") or "LLM edit")[:120],
                     "generator": generator, "parent": parent})
    return {"generator": generator, "n_proposed": len(proposals or []), "n_generated": len(kept),
            "n_rejected": len(rejected), "molecules": kept, "rejected": rejected[:10],
            "validity": round(len(kept) / len(proposals), 4) if proposals else 0.0}


def novelty(smiles_list: List[str], reference_smiles: List[str],
            threshold: float = 0.4) -> Dict[str, Any]:
    """Novelty vs a reference set: exact-match rate and max Tanimoto per candidate."""
    from rdkit import DataStructs
    gen = AllChem.GetMorganGenerator(radius=2, fpSize=2048)
    ref_mols = [Chem.MolFromSmiles(s) for s in reference_smiles]
    ref_fps = [gen.GetFingerprint(m) for m in ref_mols if m is not None]
    ref_set = {Chem.MolToSmiles(m) for m in ref_mols if m is not None}
    rows = []
    for s in smiles_list:
        m = Chem.MolFromSmiles(s)
        if m is None:
            continue
        can = Chem.MolToSmiles(m)
        sims = DataStructs.BulkTanimotoSimilarity(gen.GetFingerprint(m), ref_fps) if ref_fps else [0.0]
        mx = max(sims) if sims else 0.0
        rows.append({"smiles": can, "in_reference": can in ref_set,
                     "max_tanimoto_to_reference": round(float(mx), 4),
                     "novel_at_threshold": bool(mx < threshold and can not in ref_set)})
    n = len(rows) or 1
    return {"n": len(rows), "threshold": threshold,
            "n_exact_duplicates": sum(r["in_reference"] for r in rows),
            "frac_novel": round(sum(r["novel_at_threshold"] for r in rows) / n, 4),
            "mean_max_similarity": round(sum(r["max_tanimoto_to_reference"] for r in rows) / n, 4),
            "rows": rows}


def register(registry, config):
    t = registry.tool
    t("generators.rule_decorate", VERSION, license="BSD-3-Clause (RDKit)", default_tag="COMPUTED",
      schema={"seed_smiles": "str", "n": "int"})(rule_decorate)
    t("generators.brics_recombine", VERSION, license="BSD-3-Clause (RDKit)", default_tag="COMPUTED",
      cost_hint="medium", schema={"smiles_list": "list[str]", "n": "int"})(brics_recombine)
    t("generators.selfies_mutate", VERSION, license="Apache-2.0 (selfies)", default_tag="COMPUTED",
      schema={"seed_smiles": "str", "n": "int"})(selfies_mutate)
    t("generators.validate_proposals", VERSION, license="BSD-3-Clause (RDKit)",
      default_tag="COMPUTED", schema={"proposals": "list[dict]"})(validate_proposals)
    t("generators.novelty", VERSION, license="BSD-3-Clause (RDKit)", default_tag="COMPUTED",
      schema={"smiles_list": "list[str]", "reference_smiles": "list[str]"})(novelty)
    return registry
