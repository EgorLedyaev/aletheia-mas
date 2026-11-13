"""Provenance primitives.

Every value that reaches a user passes through :class:`Evidence`. The four tags are the
contract with the reader:

COMPUTED    a deterministic tool produced this number (RDKit descriptor, Vina score, RMSD).
            Requires tool, tool_version and params_hash so the run can be repeated.
PREDICTED   a statistical model produced this number. Requires an applicability-domain
            verdict, and an uncertainty estimate unless `uncertainty_unavailable` is
            explicitly stated in `note`.
RETRIEVED   a database record. Requires source_id (accession) and retrieved_at (date).
HYPOTHESIS  LLM reasoning. May NOT carry a numeric payload -- this is what stops a model
            from inventing an IC50 and dressing it as a conclusion.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class EvidenceTag(str, Enum):
    COMPUTED = "COMPUTED"
    PREDICTED = "PREDICTED"
    RETRIEVED = "RETRIEVED"
    HYPOTHESIS = "HYPOTHESIS"


class Applicability(str, Enum):
    IN_DOMAIN = "IN_DOMAIN"
    BORDERLINE = "BORDERLINE"
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
    NOT_ASSESSED = "NOT_ASSESSED"


def utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def params_hash(params: Dict[str, Any]) -> str:
    """Stable hash of tool parameters, used for cache keys and reproducibility."""
    blob = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{datetime.datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"


class Uncertainty(BaseModel):
    kind: str                      # "conformal" | "ensemble_std" | "interval" | "class_prob"
    lower: Optional[float] = None
    upper: Optional[float] = None
    level: Optional[float] = None  # e.g. 0.9 for a 90% interval
    std: Optional[float] = None
    note: Optional[str] = None


class Evidence(BaseModel):
    """One traceable value. `claim_id` is what a rendered answer must cite."""

    claim_id: str
    tag: EvidenceTag
    key: str
    value: Any = None
    units: Optional[str] = None
    subject: Optional[str] = None          # SMILES / accession / PDB id the value describes
    tool: Optional[str] = None
    tool_version: Optional[str] = None
    params_hash: Optional[str] = None
    run_id: Optional[str] = None
    call_id: Optional[str] = None
    source_id: Optional[str] = None        # CHEMBL25 / P00533 / 1M17 / DOI
    source_url: Optional[str] = None
    retrieved_at: Optional[str] = None
    uncertainty: Optional[Uncertainty] = None
    applicability: Applicability = Applicability.NOT_ASSESSED
    validation: Optional[Dict[str, Any]] = None   # e.g. {"redock_rmsd_A": 1.1, "ef1pct": 3.2}
    note: Optional[str] = None
    created_at: str = Field(default_factory=utcnow)

    model_config = {"use_enum_values": False}

    @field_validator("key")
    @classmethod
    def _key_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Evidence.key must be a non-empty label")
        return v.strip()

    @model_validator(mode="after")
    def _tag_requirements(self) -> "Evidence":
        tag = self.tag
        if tag == EvidenceTag.COMPUTED:
            missing = [f for f in ("tool", "tool_version", "params_hash") if not getattr(self, f)]
            if missing:
                raise ValueError(f"COMPUTED evidence '{self.key}' is missing {missing}; "
                                 "a computed number must be reproducible")
        elif tag == EvidenceTag.PREDICTED:
            if not self.tool or not self.tool_version:
                raise ValueError(f"PREDICTED evidence '{self.key}' needs tool and tool_version")
            if self.applicability == Applicability.NOT_ASSESSED and not (self.note or ""):
                raise ValueError(f"PREDICTED evidence '{self.key}' needs an applicability verdict "
                                 "or an explicit note saying why it was not assessed")
            if self.uncertainty is None and "uncertainty_unavailable" not in (self.note or ""):
                raise ValueError(f"PREDICTED evidence '{self.key}' needs an uncertainty estimate, "
                                 "or note='uncertainty_unavailable: <reason>'")
        elif tag == EvidenceTag.RETRIEVED:
            if not self.source_id or not self.retrieved_at:
                raise ValueError(f"RETRIEVED evidence '{self.key}' needs source_id and retrieved_at")
        elif tag == EvidenceTag.HYPOTHESIS:
            if isinstance(self.value, (int, float)) and not isinstance(self.value, bool):
                raise ValueError(
                    f"HYPOTHESIS evidence '{self.key}' carries a numeric value "
                    f"({self.value!r}). Numbers must come from a tool, not from reasoning."
                )
            if not self.note:
                raise ValueError(f"HYPOTHESIS evidence '{self.key}' needs a note with the reasoning")
        return self

    def render_value(self, precision: int = 3) -> str:
        v = self.value
        if isinstance(v, float):
            s = f"{v:.{precision}f}".rstrip("0").rstrip(".")
            return s if s not in ("", "-") else "0"
        if isinstance(v, (list, tuple)):
            return ", ".join(str(x) for x in v)
        return str(v)

    def badge(self) -> str:
        """Short human-facing provenance badge used by the reporter."""
        bits = [self.tag.value]
        if self.tag == EvidenceTag.COMPUTED and self.tool:
            bits.append(f"{self.tool} {self.tool_version or ''}".strip())
        if self.tag == EvidenceTag.PREDICTED:
            if self.tool:
                bits.append(f"{self.tool} {self.tool_version or ''}".strip())
            bits.append(f"AD={self.applicability.value}")
            if self.uncertainty and self.uncertainty.lower is not None:
                lvl = f"{int((self.uncertainty.level or 0) * 100)}%" if self.uncertainty.level else ""
                bits.append(f"{lvl}CI[{self.uncertainty.lower:.2f},{self.uncertainty.upper:.2f}]")
        if self.tag == EvidenceTag.RETRIEVED and self.source_id:
            day = (self.retrieved_at or "")[:10]
            bits.append(f"{self.source_id} @ {day}" if day else str(self.source_id))
        return " | ".join(b for b in bits if b)


class ToolCallRecord(BaseModel):
    """Audit record for one tool invocation; the ledger links claims back to these."""
    call_id: str
    tool: str
    tool_version: str
    params: Dict[str, Any] = {}
    params_hash: str
    started_at: str
    duration_s: float
    cached: bool = False
    ok: bool = True
    error: Optional[str] = None
    n_evidence: int = 0
    agent: Optional[str] = None
