"""Baselines the multi-agent system has to beat, and the fabrication measure that compares them.

B1  plain LLM, no tools          -- the question goes straight to the model
B2  single agent with tools      -- one LLM in a ReAct-style loop over the same tool registry

The comparison metric is not "which answer reads better" but **identifier verifiability**: every
ChEMBL id, PDB id and UniProt accession in an answer is checked against the live databases, and
every number is checked for provenance. A plain LLM has no provenance by construction; a single
tool-using agent has some; Aletheia is required to have 100% or the answer is withheld.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

CHEMBL_RE = re.compile(r"\bCHEMBL\d+\b")
PDB_RE = re.compile(r"\b(?:PDB[:\s]+)?([0-9][A-Za-z0-9]{3})\b")
UNIPROT_RE = re.compile(r"\b([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9][A-Z][A-Z0-9]{2}[0-9])\b")
NUM_RE = re.compile(r"(?<![A-Za-z0-9_.^])[-+]?\d+(?:\.\d+)?(?![A-Za-z0-9_])")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
STOP_PDB = {"IC50", "ADME", "LOGP", "QSAR"}


def verify_identifiers(text: str, timeout: int = 30) -> Dict[str, Any]:
    """Check every database identifier mentioned in a free-text answer against the live source."""
    from ..tools.http import get_json
    found = {"chembl": sorted(set(CHEMBL_RE.findall(text))),
             "uniprot": sorted(set(UNIPROT_RE.findall(text))),
             "pdb": sorted({m.group(1).upper() for m in PDB_RE.finditer(text)
                            if m.group(1).upper() not in STOP_PDB
                            and not re.match(r"^\d{4}$", m.group(1))})}
    checked: List[Dict[str, Any]] = []
    for cid in found["chembl"][:12]:
        # A CHEMBL id can name a molecule, a target, an assay or a document. Checking only the
        # molecule endpoint would mark a legitimate target id (CHEMBL203 = EGFR) as fabricated,
        # so every entity type is tried before an id is called nonexistent. A server error or a
        # network failure means UNVERIFIABLE, never nonexistent: during the 2026-11-12 ChEMBL
        # outage the first version of this checker reported 40% of one baseline's identifiers as
        # fabricated when every one of them existed.
        ok, detail, kind = False, "not found in molecule/target/assay/document", "chembl"
        unreachable = False
        for entity, label in (("molecule", "molecule"), ("target", "target"),
                              ("assay", "assay"), ("document", "document")):
            try:
                d = get_json(f"https://www.ebi.ac.uk/chembl/api/data/{entity}/{cid}.json",
                             timeout=timeout)
                ok = True
                detail = f"{label}: " + str(d.get("pref_name") or d.get("description")
                                            or d.get("title") or cid)[:50]
                break
            except Exception as exc:
                msg = str(exc)
                if "HTTP 5" in msg or "Connection" in msg or "Timeout" in msg:
                    unreachable = True
                    detail = f"source unreachable ({msg[:40]})"
                    break
        checked.append({"kind": kind, "id": cid, "exists": ok, "detail": str(detail)[:60],
                        "unverifiable": bool(unreachable and not ok)})
    for acc in found["uniprot"][:12]:
        ok, detail = True, ""
        try:
            d = get_json(f"https://rest.uniprot.org/uniprotkb/{acc}.json?fields=accession,protein_name",
                         timeout=timeout)
            detail = d.get("primaryAccession", "")
        except Exception as exc:
            ok, detail = False, type(exc).__name__
            unreachable = ("HTTP 5" in str(exc) or "Connection" in str(exc)
                           or "Timeout" in str(exc))
        checked.append({"kind": "uniprot", "id": acc, "exists": ok, "detail": str(detail)[:60],
                        "unverifiable": bool(locals().get("unreachable") and not ok)})
    for pid in found["pdb"][:12]:
        ok, detail = True, ""
        try:
            d = get_json(f"https://data.rcsb.org/rest/v1/core/entry/{pid}", timeout=timeout)
            detail = ((d.get("struct") or {}).get("title") or "")[:50]
        except Exception as exc:
            ok, detail = False, type(exc).__name__
            unreachable = ("HTTP 5" in str(exc) or "Connection" in str(exc)
                           or "Timeout" in str(exc))
        checked.append({"kind": "pdb", "id": pid, "exists": ok, "detail": str(detail)[:60],
                        "unverifiable": bool(locals().get("unreachable") and not ok)})
    unverifiable = [c for c in checked if c.get("unverifiable")]
    verifiable = [c for c in checked if not c.get("unverifiable")]
    n = len(verifiable)
    bad = [c for c in verifiable if not c["exists"]]
    scrub = DATE_RE.sub(" ", text)
    for pat in (CHEMBL_RE, UNIPROT_RE):
        scrub = pat.sub(" ", scrub)
    scrub = PDB_RE.sub(" ", scrub)
    numbers = [m.group() for m in NUM_RE.finditer(scrub)]
    return {"identifiers_found": len(checked), "identifiers_checked": checked,
            "n_verifiable": n, "n_unverifiable": len(unverifiable),
            "n_nonexistent": len(bad), "nonexistent": bad,
            "identifier_error_rate": round(len(bad) / n, 4) if n else None,
            "n_numeric_tokens": len(numbers),
            "numeric_tokens": numbers[:40]}


def plain_llm(query: str, ctx_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """B1: no tools, no retrieval, no ledger -- exactly what a chat model would answer."""
    from ..core.llm import LLMClient
    llm = LLMClient(ctx_cfg)
    t0 = time.time()
    resp = llm.complete(
        query, system=("You are a computational chemistry assistant. Answer the request directly "
                       "and concretely, with specific identifiers and numbers where relevant."),
        purpose="baseline_plain_llm", max_tokens=1200)
    dt = round(time.time() - t0, 2)
    text = resp.text or ""
    ver = verify_identifiers(text)
    return {"baseline": "B1_plain_llm", "query": query, "answer": text, "duration_s": dt,
            "backend": resp.backend, "cached": resp.cached, "error": resp.error,
            "n_tool_calls": 0, "provenance": "none: no tool produced any value in this answer",
            "ledger_coverage": 0.0 if ver["n_numeric_tokens"] else None, **ver}


TOOL_PICK_SCHEMA = {
    "name": "pick_tool",
    "description": "Choose the next tool to call, or finish.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["call_tool", "finish"]},
            "tool": {"type": "string"},
            "arguments_json": {"type": "string",
                               "description": "JSON object of arguments for the tool."},
            "answer": {"type": "string", "description": "Final answer when action is finish."},
        },
        "required": ["action"],
    },
}


def single_agent(query: str, cfg: Dict[str, Any], max_steps: int = 8) -> Dict[str, Any]:
    """B2: one LLM agent with the same tool registry, no planner, no critic, no ledger discipline."""
    from ..core.context import RunContext
    ctx = RunContext(query, cfg)
    t0 = time.time()
    catalogue = "\n".join(f"- {t['name']}({', '.join(t['schema'].keys())}) : {t['description'][:80]}"
                          for t in ctx.tools.describe())
    transcript: List[str] = []
    calls = 0
    answer = ""
    for step in range(max_steps):
        prompt = (f"Request: {query}\n\nAvailable tools:\n{catalogue}\n\n"
                  f"Work so far:\n" + ("\n".join(transcript[-6:]) or "(nothing yet)") +
                  "\n\nPick the next tool call, or finish with a complete answer.")
        out = ctx.llm.structured(prompt, TOOL_PICK_SCHEMA,
                                 system="You are a single chemistry agent with tool access.",
                                 deterministic=lambda: {"action": "finish",
                                                        "answer": "no LLM backend available"},
                                 purpose="baseline_single_agent", max_tokens=900)
        d = out.get("data") or {}
        if d.get("action") != "call_tool" or not d.get("tool"):
            answer = d.get("answer") or ""
            break
        try:
            kwargs = json.loads(d.get("arguments_json") or "{}")
        except json.JSONDecodeError:
            kwargs = {}
        if d["tool"] not in ctx.tools.specs:
            transcript.append(f"ERROR: no tool named {d['tool']}")
            continue
        res = ctx.tools.call(d["tool"], agent="single_agent", **kwargs)
        calls += 1
        payload = json.dumps(res.data, default=str)[:700] if res.ok else f"ERROR {res.error}"
        transcript.append(f"{d['tool']}({kwargs}) -> {payload}")
    if not answer:
        fin = ctx.llm.complete(
            f"Request: {query}\n\nTool results:\n" + "\n".join(transcript[-8:]) +
            "\n\nWrite the final answer.", purpose="baseline_single_agent_final", max_tokens=1000)
        answer = fin.text or ""
    ver = verify_identifiers(answer)
    return {"baseline": "B2_single_agent", "query": query, "answer": answer,
            "duration_s": round(time.time() - t0, 2), "n_tool_calls": calls,
            "n_llm_calls": len(ctx.llm.calls), "run_id": ctx.run_id,
            "transcript": transcript, "provenance": "tool calls happened but no claim is bound to "
                                                    "a value in the answer text", **ver}
