"""Claims ledger + the verifier that blocks untraceable answers.

Rule enforced here (the project's central promise):
    a number, interval or structure that appears in a final answer must resolve to an
    Evidence record produced by a tool run. If it does not, the answer is BLOCKED.

The verifier is deliberately mechanical -- no LLM is involved in deciding whether a claim
is supported, because an LLM judge can be talked out of a refusal.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel

from .provenance import Evidence, EvidenceTag, ToolCallRecord

# A number, with optional sign, decimals, exponent, percent.
# `^` is excluded from the lookbehind so unit labels such as A^2 / A^3 are not read as claims.
NUM_RE = re.compile(r"(?<![A-Za-z0-9_.^])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])")
CLAIM_REF_RE = re.compile(r"\[(E-\d{4,})\]")
# ISO-8601 dates/timestamps carry digits that are metadata, not claims; scrubbed before scanning.
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?")
# Identifier shapes we must not mistake for free-floating numbers.
ID_RE = re.compile(r"\b(?:CHEMBL\d+|CID\s?\d+|[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2}"
                   r"|[0-9][A-Za-z0-9]{3}|10\.\d{4,9}/\S+|run-\d{8}T\d{6}-[0-9a-f]+|E-\d{4,})\b")

OVERCLAIM_PATTERNS = [
    (r"\bguarantee(?:d|s)?\b", "guarantee"),
    (r"\bproven\b", "proven"),
    (r"\bprov(?:es|ed)\s+(?:that|to)\b", "proves"),
    (r"\bwill\s+(?:cure|work|bind|succeed)\b", "will-cure"),
    (r"\b100\s?%\s+(?:safe|effective|selective)\b", "absolute-safety"),
    (r"\bno\s+side\s+effects\b", "no-side-effects"),
    (r"\bclinically\s+validated\b", "clinically-validated"),
    (r"\bready\s+for\s+(?:clinical|human)\b", "ready-for-clinic"),
    (r"\bconfirmed\s+(?:hit|active|binder)\b", "confirmed-hit"),
]


class Violation(BaseModel):
    kind: str          # UNTRACEABLE_NUMBER | UNCITED_BLOCK | UNKNOWN_STRUCTURE | OVERCLAIM | BAD_CLAIM_REF
    detail: str
    block: Optional[str] = None
    token: Optional[str] = None


class VerificationReport(BaseModel):
    ok: bool
    violations: List[Violation] = []
    n_blocks: int = 0
    n_numeric_tokens: int = 0
    n_resolved_tokens: int = 0
    n_claims_used: int = 0
    n_claims_total: int = 0

    @property
    def numeric_coverage(self) -> float:
        return 1.0 if self.n_numeric_tokens == 0 else self.n_resolved_tokens / self.n_numeric_tokens

    def summary(self) -> str:
        return (f"ledger coverage {self.numeric_coverage*100:.1f}% "
                f"({self.n_resolved_tokens}/{self.n_numeric_tokens} numeric tokens), "
                f"{self.n_claims_used}/{self.n_claims_total} claims cited, "
                f"{len(self.violations)} violation(s)")


class LedgerViolation(RuntimeError):
    def __init__(self, report: VerificationReport):
        self.report = report
        lines = [f"{v.kind}: {v.detail}" for v in report.violations[:12]]
        super().__init__("answer blocked by claims ledger -- " + report.summary() + "\n  " +
                         "\n  ".join(lines))


def _numbers_in(value: Any) -> List[float]:
    """All numbers reachable inside an evidence value (scalars, lists, dicts, numeric strings)."""
    out: List[float] = []
    if isinstance(value, bool):
        return out
    if isinstance(value, (int, float)):
        out.append(float(value))
    elif isinstance(value, str):
        for m in NUM_RE.finditer(value):
            try:
                out.append(float(m.group()))
            except ValueError:
                pass
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_numbers_in(v))
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            out.extend(_numbers_in(v))
    return out


def _evidence_numbers(ev: Evidence) -> List[float]:
    nums = _numbers_in(ev.value)
    if ev.uncertainty is not None:
        for f in ("lower", "upper", "std", "level"):
            x = getattr(ev.uncertainty, f, None)
            if isinstance(x, (int, float)):
                nums.append(float(x))
    if ev.validation:
        nums.extend(_numbers_in(ev.validation))
    return nums


def _matches(token: str, pool: Sequence[float]) -> bool:
    """Does a printed token match any pooled number, allowing for display rounding?"""
    try:
        x = float(token)
    except ValueError:
        return False
    if "." in token:
        dec = len(token.split(".")[1].split("e")[0].split("E")[0])
    else:
        dec = 0
    tol = max(0.5 * 10 ** (-dec), abs(x) * 1e-9)
    # Primary test: does the ledger value, *printed at the token's precision*, equal the token?
    # This is exactly the operation the reporter performed, so it is immune to the
    # half-ulp boundary cases that a plain tolerance comparison gets wrong
    # (f"{0.3385:.3f}" == "0.339" while |0.3385 - 0.339| is 5e-4 + 4e-19).
    for p in pool:
        try:
            if f"{p:.{dec}f}" == f"{x:.{dec}f}":
                return True
        except (ValueError, OverflowError):
            pass
        # percentages: a fraction of 0.37 may legitimately print as 37
        if abs(p - x) <= tol or abs(p * 100.0 - x) <= max(tol, abs(x) * 1e-6) or (
                p != 0 and abs(p - x / 100.0) <= 1e-9):
            return True
    return False


class ClaimsLedger:
    """Append-only store of Evidence, keyed by claim_id (E-0001, E-0002, ...)."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._claims: Dict[str, Evidence] = {}
        self._calls: Dict[str, ToolCallRecord] = {}
        self._n = 0

    # -- writing -------------------------------------------------------------
    def next_id(self) -> str:
        self._n += 1
        return f"E-{self._n:04d}"

    def register(self, **kwargs: Any) -> Evidence:
        """Create, validate and store one Evidence record. Raises on contract breach.

        The claim id is assigned only after validation succeeds, so a rejected record does not
        leave a hole in the numbering (an audit reader should never have to wonder what E-0001 was).
        """
        explicit = kwargs.get("claim_id")
        kwargs.setdefault("claim_id", "E-0000")
        kwargs.setdefault("run_id", self.run_id)
        ev = Evidence(**kwargs)
        if not explicit:
            ev.claim_id = self.next_id()
        self._claims[ev.claim_id] = ev
        if ev.call_id and ev.call_id in self._calls:
            self._calls[ev.call_id].n_evidence += 1
        return ev

    def register_evidence(self, ev: Evidence) -> Evidence:
        self._claims[ev.claim_id] = ev
        return ev

    def record_call(self, rec: ToolCallRecord) -> ToolCallRecord:
        self._calls[rec.call_id] = rec
        return rec

    # -- reading -------------------------------------------------------------
    def get(self, claim_id: str) -> Optional[Evidence]:
        return self._claims.get(claim_id)

    @property
    def claims(self) -> Dict[str, Evidence]:
        return dict(self._claims)

    @property
    def calls(self) -> Dict[str, ToolCallRecord]:
        return dict(self._calls)

    def by_tag(self, tag: EvidenceTag) -> List[Evidence]:
        return [e for e in self._claims.values() if e.tag == tag]

    def subjects(self) -> List[str]:
        out = []
        for e in self._claims.values():
            if e.subject:
                out.append(e.subject)
            if isinstance(e.value, str):
                out.append(e.value)
            if isinstance(e.value, (list, tuple)):
                out.extend([str(v) for v in e.value])
        return out

    def identifiers(self) -> List[str]:
        out = []
        for e in self._claims.values():
            for f in ("source_id", "subject"):
                v = getattr(e, f, None)
                if v:
                    out.append(str(v))
            if isinstance(e.value, str):
                out.append(e.value)
            if isinstance(e.value, (list, tuple)):
                out.extend(str(v) for v in e.value)
            if isinstance(e.value, dict):
                out.extend(str(v) for v in e.value.values())
                out.extend(str(k) for k in e.value.keys())
        return out

    def to_rows(self) -> List[Dict[str, Any]]:
        rows = []
        for cid, e in sorted(self._claims.items()):
            rows.append({
                "claim_id": cid, "tag": e.tag.value, "key": e.key,
                "value": e.render_value(), "units": e.units or "", "subject": e.subject or "",
                "tool": e.tool or "", "tool_version": e.tool_version or "",
                "source_id": e.source_id or "", "params_hash": e.params_hash or "",
                "call_id": e.call_id or "", "applicability": e.applicability.value,
                "uncertainty": (e.uncertainty.model_dump() if e.uncertainty else None),
                "validation": e.validation, "note": e.note or "",
            })
        return rows


class AnswerVerifier:
    """Scans rendered answer blocks and blocks anything the ledger cannot support."""

    def __init__(self, ledger: ClaimsLedger, strict_citation: bool = True,
                 allow_global_pool: bool = True):
        self.ledger = ledger
        self.strict_citation = strict_citation      # every block must cite >=1 claim
        self.allow_global_pool = allow_global_pool  # numbers may resolve against any claim

    def verify(self, blocks: Iterable[Any]) -> VerificationReport:
        blocks = list(blocks)
        violations: List[Violation] = []
        n_tokens = n_resolved = 0
        used: set = set()
        global_pool: List[float] = []
        if self.allow_global_pool:
            for e in self.ledger.claims.values():
                global_pool.extend(_evidence_numbers(e))
        # Tool versions, accessions and parameter hashes are provenance metadata that the reporter
        # prints inside provenance badges. Their digits are not claims, so they are always
        # resolvable -- otherwise printing "vina 1.2.7" would look like an unsupported number.
        meta_pool: List[float] = []
        for e in self.ledger.claims.values():
            for field in (e.tool_version, e.source_id, e.params_hash, e.tool):
                if isinstance(field, str):
                    meta_pool.extend(_numbers_in(field))
        known_ids = {str(s).upper() for s in self.ledger.identifiers()}

        for b in blocks:
            text = getattr(b, "text", str(b))
            cited = list(getattr(b, "claim_ids", []) or [])
            exempt = set(getattr(b, "exempt_numbers", []) or [])
            structures = list(getattr(b, "structures", []) or [])
            label = (getattr(b, "title", None) or text[:40])

            for cid in cited:
                if self.ledger.get(cid) is None:
                    violations.append(Violation(kind="BAD_CLAIM_REF",
                                                detail=f"block '{label}' cites unknown claim {cid}",
                                                block=label, token=cid))
                else:
                    used.add(cid)

            uncited_probe = ID_RE.sub(" ", DATE_RE.sub(" ", text))
            uncited_nums = [m.group() for m in NUM_RE.finditer(uncited_probe)]
            if self.strict_citation and not cited and \
                    any(t not in exempt for t in uncited_nums):
                violations.append(Violation(kind="UNCITED_BLOCK",
                                            detail=f"block '{label}' states numbers but cites no claim",
                                            block=label))

            pool: List[float] = []
            for cid in cited:
                ev = self.ledger.get(cid)
                if ev:
                    pool.extend(_evidence_numbers(ev))
            pool = pool + meta_pool
            if self.allow_global_pool:
                pool = pool + global_pool

            scrub = ID_RE.sub(" ", DATE_RE.sub(" ", CLAIM_REF_RE.sub(" ", text)))
            for m in NUM_RE.finditer(scrub):
                tok = m.group()
                n_tokens += 1
                if tok in exempt or _matches(tok, pool):
                    n_resolved += 1
                else:
                    violations.append(Violation(
                        kind="UNTRACEABLE_NUMBER",
                        detail=f"'{tok}' in block '{label}' resolves to no ledger claim",
                        block=label, token=tok))

            for s in structures:
                if str(s).upper() not in known_ids and str(s) not in self.ledger.subjects():
                    violations.append(Violation(
                        kind="UNKNOWN_STRUCTURE",
                        detail=f"structure/identifier '{s}' in block '{label}' is not in the ledger",
                        block=label, token=str(s)))

            low = text.lower()
            for pat, name in OVERCLAIM_PATTERNS:
                if re.search(pat, low):
                    violations.append(Violation(kind="OVERCLAIM",
                                                detail=f"overclaiming phrase '{name}' in block '{label}'",
                                                block=label, token=name))

        return VerificationReport(
            ok=not violations, violations=violations, n_blocks=len(blocks),
            n_numeric_tokens=n_tokens, n_resolved_tokens=n_resolved,
            n_claims_used=len(used), n_claims_total=len(self.ledger.claims),
        )

    def enforce(self, blocks: Iterable[Any]) -> VerificationReport:
        rep = self.verify(blocks)
        if not rep.ok:
            raise LedgerViolation(rep)
        return rep
