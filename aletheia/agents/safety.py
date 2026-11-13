"""Safety & Guardrail agent -- a gate, not a prompt.

It runs twice in every campaign:
  1. before planning, on the natural-language request (intent gate);
  2. after generation, on every proposed structure (structure gate, via hazard.screen_batch).

Decision table (documented in docs/safety_policy.md):

| category                                   | verdict            | downstream effect                |
|--------------------------------------------|--------------------|----------------------------------|
| chemical/biological weapon, toxin as weapon | REFUSE             | run stops, nothing is planned    |
| controlled-substance synthesis/optimisation | REFUSE             | run stops                        |
| self-harm / harm to others                  | REFUSE             | run stops                        |
| evasion of detection / regulation           | REFUSE             | run stops                        |
| therapeutic design naming a hazardous class | ALLOW_WITH_NOTE    | hazard screen forced on outputs  |
| ordinary therapeutic discovery              | ALLOW              | normal execution                 |

The deterministic lexicon is the floor: if it fires, the LLM's opinion cannot lift the refusal.
The LLM can only *add* caution, never remove it. Every decision is appended to
logs/safety_events.jsonl with the query hash, so refusals are auditable after the fact.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from ..core.contracts import AgentResult, SafetyVerdict
from ..core.context import RunContext
from .base import Agent

REFUSE_RULES: List[Dict[str, Any]] = [
    {"category": "chemical_weapon",
     "patterns": [r"\bnerve agent", r"\bsarin\b", r"\bsoman\b", r"\btabun\b", r"\bvx\b",
                  r"\bnovichok", r"\bmustard gas", r"\blewisite", r"\bphosgene\b.*\b(make|synth|produce)",
                  r"\bchemical weapon", r"\bcwc\s*schedule\s*1", r"\bwar gas"],
     "detail": "chemical-weapon agent or class"},
    {"category": "biological_weapon",
     "patterns": [r"\bbio(?:logical)?\s*weapon", r"\bweaponi[sz]e", r"\branin\b", r"\bricin\b",
                  r"\babrin\b", r"\bbotulinum\b.*\b(weapon|dose|lethal|aerosol)",
                  r"\banthrax\b.*\b(weapon|aerosol|disperse)", r"\bselect agent\b.*\b(obtain|make|produce)",
                  r"\benhance\b.*\b(transmissib|virulen|lethal)"],
     "detail": "biological-weapon or pathogen-enhancement intent"},
    {"category": "toxin_for_harm",
     "patterns": [r"\b(most|highly)\s+(?:lethal|toxic|poisonous)\b.*\b(human|person|people|someone)",
                  r"\buntraceable\s+poison", r"\blethal dose\b.*\b(human|person|someone)",
                  r"\bpoison\b.*\b(someone|a person|my\b)", r"\bkill\b.*\b(someone|a person|people)\b"],
     "detail": "toxin or poison aimed at harming a person"},
    {"category": "controlled_substance",
     # The windows are deliberately wide: a request that mentions a controlled substance class
     # together with making it, improving it, or routing around scheduling is refused regardless
     # of word order.
     "patterns": [r"\b(synthes|produc|manufactur|make|cook)\w*\b.{0,80}\b(fentanyl|carfentanil|"
                  r"methamphetamine|amphetamine|mdma|lsd|heroin|cocaine|captagon|krokodil)\b",
                  r"\b(fentanyl|carfentanil|methamphetamine|mdma|lsd|heroin|cocaine|captagon)\b"
                  r".{0,80}\b(route|precursor|synthesis|synthesise|synthesize|recipe|yield|"
                  r"potency|potent|optimis|optimiz|improve|scale)\w*\b",
                  r"\b(optimis|optimiz|improve|increase|boost|design|generate|make)\w*\b.{0,80}"
                  r"\b(fentanyl|carfentanil|methamphetamine|mdma|lsd|heroin|cocaine|captagon)\b",
                  r"\b(novel|new|designer)\b.{0,40}\b(opioid|cannabinoid|cathinone|psychedelic|"
                  r"benzodiazepine)\b.{0,80}\b(evade|legal|bypass|scheduling|unscheduled|"
                  r"controlled|detection)\b",
                  r"\bresearch chemical\b.{0,40}\b(legal|evade|loophole|unscheduled)\b",
                  r"\b(scheduled|controlled)\s+precursor", r"\bavoid\w*\b.{0,40}\bscheduled\b"],
     "detail": "controlled-substance synthesis, production, potency optimisation or "
               "scheduling evasion"},
    {"category": "harm",
     "patterns": [r"\bhow (?:to|do i) (?:harm|hurt|kill)\b", r"\bsuicide\b.*\b(method|dose|how)",
                  r"\bself[- ]harm\b.*\b(method|how)"],
     "detail": "request aimed at harm to self or others"},
    {"category": "evasion",
     "patterns": [r"\bevade\b.{0,25}\b(detection|screening|customs|drug test|regulat)",
                  r"\bundetectable\b.{0,25}\b(by|in)\b.{0,20}\b(assay|screen|test)",
                  r"\bbypass\b.{0,25}\b(regulat|control|scheduling|export control)"],
     "detail": "evasion of detection or regulatory control"},
]

CAUTION_TERMS = [
    "toxin", "toxicity", "poison", "venom", "organophosphate", "nerve", "opioid", "fentanyl",
    "cannabinoid", "benzodiazepine", "amphetamine", "explosive", "pathogen", "virus", "toxoid",
]

SAFETY_SCHEMA = {
    "name": "safety_review",
    "description": "Classify the safety posture of a scientific request.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["ALLOW", "ALLOW_WITH_NOTE", "REFUSE"]},
            "category": {"type": "string",
                         "enum": ["ordinary_research", "dual_use_context", "chemical_weapon",
                                  "biological_weapon", "toxin_for_harm", "controlled_substance",
                                  "harm", "evasion"]},
            "reason": {"type": "string", "description": "One sentence, factual."},
        },
        "required": ["verdict", "category", "reason"],
    },
}

SYSTEM = (
    "You review requests sent to an automated drug-discovery system for misuse potential. "
    "Therapeutic discovery, target analysis, ADMET and toxicity *prediction*, and safety "
    "assessment are ordinary research and must be ALLOWed. REFUSE only requests seeking "
    "chemical or biological weapons, toxins intended to harm, controlled-substance production "
    "or scheduling evasion, harm to people, or evasion of detection/regulation. "
    "Answer with the tool only."
)


class SafetyAgent(Agent):
    name = "safety"
    description = "Intent gate on requests and hazard gate on generated structures."
    tools = ["hazard.screen_batch"]

    # -- intent gate ---------------------------------------------------------
    def review_request(self, ctx: RunContext) -> Dict[str, Any]:
        q = ctx.query
        low = q.lower()
        rule_hits = []
        for rule in REFUSE_RULES:
            for pat in rule["patterns"]:
                if re.search(pat, low):
                    rule_hits.append({"category": rule["category"], "detail": rule["detail"],
                                      "pattern": pat})
                    break
        caution = sorted({t for t in CAUTION_TERMS if t in low})

        # Fail-closed fallback: if the classifier is unavailable AND the request uses
        # hazard-adjacent vocabulary, the gate REFUSES rather than waving it through. A safety
        # gate that fails open is not a safety gate.
        def _fallback() -> Dict[str, Any]:
            if caution:
                return {"verdict": "REFUSE", "category": "dual_use_context",
                        "reason": "safety classifier unavailable and the request uses "
                                  f"hazard-adjacent terms ({', '.join(caution)}); refused "
                                  "fail-closed"}
            return {"verdict": "ALLOW", "category": "ordinary_research",
                    "reason": "deterministic lexicon only (no LLM backend); no hazard vocabulary"}

        llm_out = ctx.llm.structured(
            f"Request to review:\n\"\"\"{q}\"\"\"", SAFETY_SCHEMA, system=SYSTEM,
            deterministic=_fallback, purpose="safety_review", max_tokens=350)
        llm = llm_out["data"] or {"verdict": "ALLOW", "category": "ordinary_research",
                                  "reason": "no classifier output"}

        # The lexicon is the floor; the LLM may only escalate.
        if rule_hits:
            verdict = SafetyVerdict.REFUSE
            category = rule_hits[0]["category"]
            reason = f"blocked by safety lexicon: {rule_hits[0]['detail']}"
        elif llm_out.get("fallback") and llm.get("verdict") == "REFUSE":
            verdict = SafetyVerdict.REFUSE
            category = llm.get("category", "dual_use_context")
            reason = llm.get("reason", "fail-closed refusal")
        elif llm.get("verdict") == "REFUSE":
            verdict = SafetyVerdict.REFUSE
            category = llm.get("category", "unspecified")
            reason = f"blocked by LLM safety review: {llm.get('reason', '')}"
        elif llm.get("verdict") == "ALLOW_WITH_NOTE" or caution:
            verdict = SafetyVerdict.ALLOW_WITH_NOTE
            category = llm.get("category", "dual_use_context")
            reason = llm.get("reason") or "hazard-relevant vocabulary present; structure screening enforced"
        else:
            verdict = SafetyVerdict.ALLOW
            category = "ordinary_research"
            reason = llm.get("reason") or "ordinary therapeutic research request"

        decision = {"verdict": verdict.value, "category": category, "reason": reason,
                    "lexicon_hits": rule_hits, "caution_terms": caution,
                    "llm_backend": llm_out.get("backend"), "llm_verdict": llm.get("verdict"),
                    "classifier_available": not llm_out.get("fallback", False),
                    "force_structure_screen": verdict != SafetyVerdict.ALLOW or bool(caution),
                    "query_sha256": hashlib.sha256(q.encode("utf-8")).hexdigest()[:16],
                    "policy_version": "aletheia-safety-1.0"}
        self._log(ctx, decision)
        ctx.safety = decision
        ctx.tracer.emit("safety_decision", verdict=decision["verdict"],
                        category=category, detail=reason)
        return decision

    # -- structure gate ------------------------------------------------------
    def screen_structures(self, ctx: RunContext, smiles: List[str]) -> Dict[str, Any]:
        call = ctx.tools.call("hazard.screen_batch", agent=self.name, smiles_list=list(smiles))
        if not call.ok:
            ctx.degrade(f"hazard screening unavailable: {call.error}")
            return {"ok": False, "error": call.error, "blocked_smiles": []}
        d = call.data
        if d["n_block"] or d["n_review"]:
            self._log(ctx, {"verdict": "STRUCTURE_BLOCK", "n_block": d["n_block"],
                            "n_review": d["n_review"], "blocked": d["blocked_smiles"][:20],
                            "policy_version": "aletheia-safety-1.0"})
        ctx.tracer.emit("safety_structure_screen", n=d["n_screened"], blocked=len(d["blocked_smiles"]),
                        n_note=d["n_note"])
        return {"ok": True, "call": call, **d}

    # -- audit ---------------------------------------------------------------
    def _log(self, ctx: RunContext, decision: Dict[str, Any]) -> None:
        os.makedirs("logs", exist_ok=True)
        rec = {"run_id": ctx.run_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **decision}
        with open(os.path.join("logs", "safety_events.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")

    def act(self, ctx: RunContext, step) -> AgentResult:
        t0 = time.time()
        d = self.review_request(ctx)
        ev = [self.ev(ctx, "COMPUTED", "safety_verdict", d["verdict"],
                      tool="aletheia.safety", tool_version=d["policy_version"],
                      params_hash=d["query_sha256"], note=d["reason"])]
        return AgentResult(agent=self.name, step_id=getattr(step, "step_id", "S0"),
                           ok=d["verdict"] != "REFUSE", data=d, evidence=ev,
                           messages=[f"{d['verdict']}: {d['reason']}"],
                           duration_s=round(time.time() - t0, 3))
