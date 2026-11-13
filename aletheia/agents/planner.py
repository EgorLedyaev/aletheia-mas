"""Intent & Planner agent.

Division of labour (design decision D6): the LLM decides *what* the user wants -- intents,
modality, which entities are targets and which are molecules -- and a deterministic builder
decides *how* to satisfy it, by expanding each intent into a fixed, reviewed step graph.

Rationale: letting an LLM emit arbitrary agent/tool names is the main source of broken agent
runs. Constraining it to a closed label set keeps the LLM as the control component while making
the executable plan verifiable. The same labels are produced by `rule_based_plan` when no LLM
backend is reachable, so the system degrades to deterministic routing instead of failing.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from ..core.contracts import AgentResult, Intent, Modality, Plan, PlanStep
from ..core.context import RunContext
from .base import Agent

SMILES_HINT = re.compile(r"(?<![A-Za-z0-9])(?=[^\s]*[=#\(\)1-9])[BCNOPSFIbcnops@+\-\[\]\(\)=#\\/%0-9]{6,}(?![A-Za-z0-9])")
UNIPROT_RE = re.compile(r"\b([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9][A-Z][A-Z0-9]{2}[0-9])\b")
PDB_RE = re.compile(r"\b(?:PDB[: ]?)?([0-9][A-Za-z0-9]{3})\b")
GENE_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,7})\b")

INTENT_KEYWORDS: Dict[Intent, List[str]] = {
    Intent.TARGET_BRIEF: ["target", "protein", "мишен", "белок", "about the protein", "brief"],
    Intent.LIGAND_LOOKUP: ["known inhibitors", "known actives", "actives", "chembl", "sar",
                           "ингибитор", "известн", "ligands", "drugs for"],
    Intent.PROPERTY_PROFILE: ["descriptor", "properties", "drug-likeness", "druglikeness", "qed",
                              "lipinski", "admet", "свойств", "дескриптор", "profile"],
    Intent.GENERATE_ANALOGS: ["generate", "design", "analog", "analogue", "modify", "optimis",
                              "optimiz", "сгенерир", "аналог", "новые молекул", "improve"],
    Intent.DOCKING: ["dock", "docking", "pose", "binding mode", "докинг", "vina", "affinity"],
    Intent.QSAR: ["qsar", "predict activity", "activity model", "predict ic50", "pic50", "модель"],
    Intent.RANK_CANDIDATES: ["rank", "prioriti", "shortlist", "select", "best candidates",
                             "ранжир", "portfolio"],
    Intent.PROTEIN_ANALYSIS: ["sequence", "structure", "pocket", "binding site", "alphafold",
                              "plddt", "последовательност", "структур", "карман", "fold"],
    Intent.FULL_CAMPAIGN: ["campaign", "end-to-end", "full pipeline", "from scratch",
                           "hit finding", "кампан"],
}

PLAN_SCHEMA = {
    "name": "route_request",
    "description": "Classify a drug-discovery request into intents and entities.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intents": {"type": "array", "items": {"type": "string", "enum": [i.value for i in Intent
                        if i not in (Intent.REFUSED, Intent.UNSUPPORTED)]},
                        "description": "Ordered list of what the user is asking for."},
            "modality": {"type": "string",
                         "enum": [m.value for m in Modality]},
            "targets": {"type": "array", "items": {"type": "string"},
                        "description": "Protein targets exactly as named by the user: gene symbol, "
                                       "UniProt accession or PDB id. Empty if none."},
            "molecules": {"type": "array", "items": {"type": "string"},
                          "description": "Molecules as named by the user: SMILES or compound name."},
            "objectives": {"type": "array", "items": {"type": "string"},
                           "description": "Optimisation objectives mentioned, e.g. 'improve solubility'."},
            "reasoning": {"type": "string", "description": "One sentence on why these intents."},
        },
        "required": ["intents", "modality", "targets", "molecules"],
    },
}

SYSTEM = (
    "You are the routing component of a drug-discovery multi-agent system. "
    "Classify the request into intents and extract entities. Do not answer the chemistry "
    "question itself, do not invent targets or molecules that the user did not mention, and do "
    "not guess identifiers. If the user names a gene symbol, return it verbatim."
)


def _valid_smiles(tok: str, min_heavy: int = 6) -> bool:
    """A token counts as a structure only if RDKit parses it into a real molecule."""
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")
    if UNIPROT_RE.fullmatch(tok.upper()) or PDB_RE.fullmatch(tok):
        return False
    m = Chem.MolFromSmiles(tok)
    return m is not None and m.GetNumHeavyAtoms() >= min_heavy


def _find_entities(q: str) -> Dict[str, List[str]]:
    molecules = [m.group() for m in SMILES_HINT.finditer(q) if _valid_smiles(m.group())]
    targets = UNIPROT_RE.findall(q)
    pdbs = [m.group(1).upper() for m in PDB_RE.finditer(q) if m.group(1)[0].isdigit()]
    genes = [g for g in GENE_RE.findall(q) if g not in {"SMILES", "ADMET", "QSAR", "PDB", "IC50",
                                                        "QED", "LLM", "MAS", "DNA", "RNA", "CSV",
                                                        "JSON", "EGFR_", "ADME"}]
    return {"molecules": molecules, "accessions": targets, "pdb_ids": pdbs, "genes": genes}


def rule_based_plan(query: str) -> Dict[str, Any]:
    """Deterministic routing used when no LLM backend is available (offline fallback)."""
    q = query.lower()
    intents = [i.value for i, kws in INTENT_KEYWORDS.items() if any(k in q for k in kws)]
    ents = _find_entities(query)
    if not intents:
        intents = [Intent.TARGET_BRIEF.value] if (ents["accessions"] or ents["genes"]) else \
                  [Intent.PROPERTY_PROFILE.value] if ents["molecules"] else [Intent.UNSUPPORTED.value]
    targets = ents["accessions"] + ents["pdb_ids"] + ents["genes"][:2]
    mol = ents["molecules"]
    modality = (Modality.PROTEIN.value if (targets and not mol) else
                Modality.SMALL_MOLECULE.value if (mol and not targets) else
                Modality.MIXED.value if (mol and targets) else Modality.UNKNOWN.value)
    return {"intents": intents, "modality": modality, "targets": targets, "molecules": mol,
            "objectives": [], "reasoning": "keyword routing (no LLM backend)"}


# -- deterministic step expansion -------------------------------------------
def _scoring_from_query(query: str) -> Optional[str]:
    """Which docking scoring function the request asks for, if it names one.

    The two scoring functions in the same binary are different oracles with different measured
    enrichment per receptor, so "dock with Vinardo" is a substantive instruction, not a detail.
    """
    q = (query or "").lower()
    if "vinardo" in q:
        return "vinardo"
    if "vina scoring" in q or "default vina" in q:
        return "vina"
    return None


def _steps_for(intents: List[str], targets: List[str], molecules: List[str],
               objectives: List[str], scoring: Optional[str] = None) -> List[PlanStep]:
    steps: List[PlanStep] = []
    n = 0

    def add(agent: str, action: str, inputs: Dict[str, Any], deps: List[str],
            optional: bool = False, why: str = "") -> str:
        nonlocal n
        n += 1
        sid = f"S{n}"
        steps.append(PlanStep(step_id=sid, agent=agent, action=action, inputs=inputs,
                              depends_on=deps, optional=optional, rationale=why))
        return sid

    want = set(intents)
    needs_target = bool(targets) and bool(
        want & {Intent.TARGET_BRIEF.value, Intent.LIGAND_LOOKUP.value, Intent.DOCKING.value,
                Intent.QSAR.value, Intent.PROTEIN_ANALYSIS.value, Intent.FULL_CAMPAIGN.value,
                Intent.GENERATE_ANALOGS.value, Intent.RANK_CANDIDATES.value})

    tgt = act = prop = gen = dock = qsar = None
    if needs_target:
        tgt = add("target_analyst", "resolve_target",
                  {"targets": targets,
                   "ligand": molecules[0] if molecules else None,
                   "need_structure": bool(want & {Intent.DOCKING.value, Intent.PROTEIN_ANALYSIS.value,
                                                  Intent.FULL_CAMPAIGN.value})},
                  [], why="every downstream claim needs a verified target identity")
    if want & {Intent.LIGAND_LOOKUP.value, Intent.QSAR.value, Intent.GENERATE_ANALOGS.value,
               Intent.FULL_CAMPAIGN.value, Intent.RANK_CANDIDATES.value}:
        act = add("chemistry_retriever", "known_actives", {"limit": 300},
                  [s for s in [tgt] if s], why="ground design in measured actives, not in LLM memory")
    if molecules or want & {Intent.PROPERTY_PROFILE.value}:
        prop = add("property_agent", "profile_molecules", {"smiles": molecules},
                   [], why="descriptors and alerts for the molecules named by the user")
    if want & {Intent.GENERATE_ANALOGS.value, Intent.FULL_CAMPAIGN.value}:
        # When the user supplies the seed molecule, generation must not depend on the chemistry
        # retriever: rule decoration, SELFIES mutation and LLM edits all work from the seed alone,
        # and making them wait on ChEMBL meant a database outage silently removed a capability
        # that does not need that database (found by the W4 baseline study, docs/negative_results
        # N9). BRICS recombination still needs retrieved actives and reports its own absence.
        gen_deps = [s for s in ([prop] if molecules else [act, prop]) if s]
        gen = add("molecule_generator", "generate",
                  {"seeds": molecules, "objectives": objectives, "n_per_generator": 40},
                  gen_deps,
                  why="three independent generators limit single-model bias")
        prop = add("property_agent", "profile_candidates", {},
                   [gen], why="cheap filters before any expensive oracle (funnel gate 1)")
    # An analogue-generation request needs a scoring oracle, otherwise the ranker has nothing to
    # rank on and the portfolio degenerates to a uniform prior. When measured actives were
    # retrieved we therefore always fit the activity proxy.
    if want & {Intent.QSAR.value, Intent.FULL_CAMPAIGN.value, Intent.GENERATE_ANALOGS.value} and act:
        # Depend on the *gate* step, not on generation: the expensive oracle must score the
        # survivors of the cheap filters, and scoring before the gate also meant the gate could
        # rebuild the candidate records and drop the scores.
        qsar = add("qsar_agent", "fit_and_predict", {},
                   [s for s in [act, prop or gen] if s],
                   why="scaffold-split activity proxy with baselines and conformal intervals")
    if want & {Intent.DOCKING.value, Intent.FULL_CAMPAIGN.value}:
        dock = add("docking_agent", "dock",
                   {"smiles": molecules, "validate": True, "scoring": scoring or "vina"},
                   [s for s in [tgt, prop] if s],
                   why="structure-based score, validated by redocking on the same receptor")
    if want & {Intent.PROTEIN_ANALYSIS.value, Intent.DOCKING.value, Intent.FULL_CAMPAIGN.value}:
        add("structure_analyst", "analyse_structure", {}, [s for s in [tgt] if s],
            why="binding-site detection on the selected structure")
    if want & {Intent.RANK_CANDIDATES.value, Intent.FULL_CAMPAIGN.value, Intent.GENERATE_ANALOGS.value}:
        add("ranker", "rank_and_select", {"k": 8},
            [s for s in [prop, qsar, dock] if s],
            why="multi-objective Pareto ranking + diversity-aware portfolio")
    steps.append(PlanStep(step_id=f"S{n+1}", agent="critic", action="cross_check",
                          inputs={}, depends_on=[s.step_id for s in steps],
                          rationale="independent recomputation and applicability-domain audit"))
    return steps


class PlannerAgent(Agent):
    name = "planner"
    description = "Classifies the request (LLM) and expands it into a verified step graph."
    tools: List[str] = []

    def plan(self, ctx: RunContext) -> Plan:
        q = ctx.query
        out = ctx.llm.structured(
            f"User request:\n\"\"\"{q}\"\"\"\n\nClassify it.", PLAN_SCHEMA, system=SYSTEM,
            deterministic=lambda: rule_based_plan(q), purpose="routing", max_tokens=900)
        data = out["data"] or rule_based_plan(q)
        # The LLM may omit entities it did not recognise; union with regex extraction.
        ents = _find_entities(q)
        targets = list(dict.fromkeys(list(data.get("targets") or []) + ents["accessions"] + ents["pdb_ids"]))
        molecules = [t for t in dict.fromkeys(list(data.get("molecules") or []) + ents["molecules"])
                     if str(t).strip()]
        intents: List[Intent] = []
        for i in data.get("intents") or []:
            try:
                intents.append(Intent(i))
            except ValueError:
                continue
        if not intents:
            intents = [Intent(i) for i in rule_based_plan(q)["intents"] if i in Intent._value2member_map_]
        try:
            modality = Modality(data.get("modality") or "unknown")
        except ValueError:
            modality = Modality.UNKNOWN
        scoring = _scoring_from_query(ctx.query)
        steps = _steps_for([i.value for i in intents], targets, molecules,
                           list(data.get("objectives") or []), scoring=scoring)
        planner_label = ("rules" if out.get("fallback") else out["backend"]) + \
                        ("+cache" if out.get("cached") else "")
        plan = Plan(query=q, intents=intents, modality=modality, targets=targets,
                    molecules=molecules, steps=steps, planner=planner_label,
                    notes=([data["reasoning"]] if data.get("reasoning") else []))
        ctx.tracer.emit("plan", intents=[i.value for i in intents], n_steps=len(steps),
                        planner=planner_label, agents=plan.agents(), targets=targets,
                        molecules=molecules[:3])
        return plan

    def act(self, ctx: RunContext, step) -> AgentResult:
        t0 = time.time()
        plan = self.plan(ctx)
        return AgentResult(agent=self.name, step_id=getattr(step, "step_id", "S0"),
                           data={"plan": plan.model_dump()},
                           messages=[f"routed to {len(plan.steps)} steps via {plan.planner}"],
                           duration_s=round(time.time() - t0, 3))
