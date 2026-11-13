"""Typed contracts exchanged between agents. Nothing crosses an agent boundary untyped."""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .provenance import Evidence


class Modality(str, Enum):
    SMALL_MOLECULE = "small_molecule"
    PROTEIN = "protein"
    NUCLEIC_ACID = "nucleic_acid"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class Intent(str, Enum):
    TARGET_BRIEF = "target_brief"              # characterise a protein target
    LIGAND_LOOKUP = "ligand_lookup"            # known actives / SAR from databases
    PROPERTY_PROFILE = "property_profile"      # descriptors / drug-likeness / ADMET of given molecules
    GENERATE_ANALOGS = "generate_analogs"      # design new or modified structures
    DOCKING = "docking"                        # pose + score against a receptor
    QSAR = "qsar"                              # build/apply an activity model
    RANK_CANDIDATES = "rank_candidates"        # multi-objective ranking / portfolio
    PROTEIN_ANALYSIS = "protein_analysis"      # sequence/structure/pocket analysis
    FULL_CAMPAIGN = "full_campaign"            # end-to-end design campaign
    REFUSED = "refused"
    UNSUPPORTED = "unsupported"


class SafetyVerdict(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_WITH_NOTE = "ALLOW_WITH_NOTE"
    REFUSE = "REFUSE"


class PlanStep(BaseModel):
    step_id: str
    agent: str
    action: str
    inputs: Dict[str, Any] = {}
    depends_on: List[str] = []
    rationale: Optional[str] = None
    optional: bool = False


class Plan(BaseModel):
    query: str
    intents: List[Intent]
    modality: Modality = Modality.UNKNOWN
    targets: List[str] = []        # UniProt accessions / gene symbols / PDB ids as given
    molecules: List[str] = []      # SMILES / names as given
    steps: List[PlanStep] = []
    planner: str = "unknown"       # which LLM backend / rule set produced this plan
    notes: List[str] = []

    def agents(self) -> List[str]:
        return list(dict.fromkeys(s.agent for s in self.steps))


class AgentResult(BaseModel):
    agent: str
    step_id: str
    ok: bool = True
    evidence: List[Evidence] = []
    data: Dict[str, Any] = {}
    messages: List[str] = []
    error: Optional[str] = None
    degraded: bool = False          # tool missing/failed but the agent continued honestly
    duration_s: float = 0.0
    source: str = "live"            # live | cached


class Candidate(BaseModel):
    """One designed or retrieved molecule travelling through the funnel."""
    cand_id: str
    smiles: str
    origin: str                                  # generator name or database
    parent: Optional[str] = None
    properties: Dict[str, Any] = {}              # key -> value
    property_claims: Dict[str, str] = {}         # key -> claim_id
    flags: List[str] = []                        # PAINS, Brenk, hazard alerts
    scores: Dict[str, float] = {}                # oracle name -> score
    score_claims: Dict[str, str] = {}
    rank: Optional[int] = None
    selected: bool = False
    notes: List[str] = []


class TargetCard(BaseModel):
    accession: Optional[str] = None
    gene: Optional[str] = None
    name: Optional[str] = None
    organism: Optional[str] = None
    length: Optional[int] = None
    sequence: Optional[str] = None
    pdb_ids: List[str] = []
    chosen_pdb: Optional[str] = None
    cocrystal_ligands: List[Dict[str, Any]] = []
    alphafold: Optional[Dict[str, Any]] = None
    pocket: Optional[Dict[str, Any]] = None
    identity_checks: List[Dict[str, Any]] = []
    claims: Dict[str, str] = {}


class AnswerBlock(BaseModel):
    """A renderable unit of the final answer. The verifier inspects exactly these."""
    title: str
    text: str
    claim_ids: List[str] = []
    structures: List[str] = []
    exempt_numbers: List[str] = []   # explicitly declared non-claims (e.g. step numbering)
    level: str = "section"           # section | note | warning


class FinalAnswer(BaseModel):
    run_id: str
    query: str
    plan: Optional[Plan] = None
    blocks: List[AnswerBlock] = []
    candidates: List[Candidate] = []
    target: Optional[TargetCard] = None
    safety: Optional[Dict[str, Any]] = None
    verification: Optional[Dict[str, Any]] = None
    ledger_rows: List[Dict[str, Any]] = []
    tool_calls: List[Dict[str, Any]] = []
    agent_results: List[Dict[str, Any]] = []
    source: str = "live"
    blocked: bool = False
    withheld_blocks: List[AnswerBlock] = []   # what the verifier refused to publish, kept for audit
    degraded: List[str] = []
    started_at: Optional[str] = None
    duration_s: float = 0.0
    cost: Dict[str, Any] = Field(default_factory=dict)

    def markdown(self) -> str:
        from .render import answer_to_markdown
        return answer_to_markdown(self)
