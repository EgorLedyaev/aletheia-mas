"""Hierarchical supervisor orchestration.

    safety gate -> planner -> dependency-ordered specialist agents (parallel where the graph
    allows) -> critic -> reporter -> claims verifier

The supervisor owns the step graph and the budget. It does not do chemistry; every decision it
makes is either a routing decision from the planner or a dependency constraint.
"""
from __future__ import annotations

import concurrent.futures as cf
import time
from typing import Any, Dict, List

from ..agents import get_agent
from ..agents.planner import PlannerAgent
from ..agents.reporter import ReporterAgent
from ..agents.safety import SafetyAgent
from ..core.contracts import AgentResult, AnswerBlock, FinalAnswer, Intent, Plan, PlanStep
from ..core.context import RunContext
from ..core.ledger import LedgerViolation


def _refusal_answer(ctx: RunContext, decision: Dict[str, Any]) -> FinalAnswer:
    block = AnswerBlock(
        title="Request refused",
        text=(f"This request was refused by the safety gate.\n\n"
              f"- Category: **{decision['category']}**\n"
              f"- Reason: {decision['reason']}\n\n"
              "No scientific tools were invoked and no molecules were generated. "
              "If the intent is legitimate therapeutic research, rephrase it as a design or "
              "analysis task for a therapeutic target and resubmit; requests of this category "
              "belong with an institutional biosafety or compliance office, not an automated "
              "design loop."),
        level="warning", claim_ids=[])
    return FinalAnswer(run_id=ctx.run_id, query=ctx.query, blocks=[block], safety=decision,
                       blocked=False, source="live", duration_s=round(ctx.elapsed, 2),
                       cost={"llm_calls": len(ctx.llm.calls), "tool_calls": 0,
                             "llm_backend": ctx.llm.backend_name})


def run_supervisor(ctx: RunContext) -> FinalAnswer:
    results: List[AgentResult] = []

    # 1. safety gate (before anything else touches the request)
    abl = ctx.cfg.get("ablation", {})
    safety = SafetyAgent()
    if abl.get("no_guardrail"):
        decision = {"verdict": "ALLOW", "category": "ABLATION_GUARDRAIL_DISABLED",
                    "reason": "guardrail ablation: the safety gate was switched off for this run",
                    "force_structure_screen": False}
        ctx.safety = decision
        ctx.tracer.emit("safety_decision", verdict="ALLOW", category="ABLATION_GUARDRAIL_DISABLED",
                        detail="ablation run")
    else:
        decision = safety.review_request(ctx)
    if decision["verdict"] == "REFUSE":
        ctx.tracer.emit("run_end", refused=True)
        return _refusal_answer(ctx, decision)

    # 2. planning
    planner = PlannerAgent()
    plan = planner.plan(ctx)
    ctx.note("targets", plan.targets)
    ctx.note("molecules", plan.molecules)
    ctx.note("objectives", plan.notes)
    if not plan.steps or Intent.UNSUPPORTED in plan.intents:
        blocks = [AnswerBlock(
            title="Request not supported",
            text=("The planner could not map this request to any capability of the system.\n\n"
                  "Supported entry points: target brief, known actives / SAR lookup, property and "
                  "ADMET profiling, analogue generation, docking with redocking validation, "
                  "activity modelling, candidate ranking, protein sequence/structure analysis."),
            level="warning")]
        return FinalAnswer(run_id=ctx.run_id, query=ctx.query, plan=plan, blocks=blocks,
                           safety=decision, duration_s=round(ctx.elapsed, 2))

    # 3. execution, respecting dependencies, parallel where possible
    done: Dict[str, AgentResult] = {}
    pending: List[PlanStep] = list(plan.steps)
    if abl.get("no_critic"):
        dropped = [s.step_id for s in pending if s.agent == "critic"]
        pending = [s for s in pending if s.agent != "critic"]
        plan.steps = [s for s in plan.steps if s.agent != "critic"]
        for s in pending:
            s.depends_on = [d for d in s.depends_on if d not in dropped]
        ctx.tracer.emit("ablation", detail="critic disabled")
    max_par = int(ctx.cfg["orchestrator"].get("max_parallel", 4))
    while pending:
        ready = [s for s in pending
                 if all(d in done for d in s.depends_on)]
        if not ready:
            for s in pending:
                ctx.degrade(f"step {s.step_id} ({s.agent}) skipped: unmet dependencies "
                            f"{[d for d in s.depends_on if d not in done]}")
            break
        if ctx.over_budget:
            for s in pending:
                ctx.degrade(f"step {s.step_id} ({s.agent}) skipped: time budget exhausted")
            break
        batch = ready[:max_par] if len(ready) > 1 else ready
        if len(batch) == 1:
            s = batch[0]
            agent = get_agent(s.agent)
            if agent is None:
                ctx.degrade(f"no agent named {s.agent}")
                done[s.step_id] = AgentResult(agent=s.agent, step_id=s.step_id, ok=False,
                                              error="agent not registered")
            else:
                done[s.step_id] = agent.run(ctx, s)
        else:
            with cf.ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futs = {}
                for s in batch:
                    agent = get_agent(s.agent)
                    if agent is None:
                        done[s.step_id] = AgentResult(agent=s.agent, step_id=s.step_id, ok=False,
                                                      error="agent not registered")
                        continue
                    futs[pool.submit(agent.run, ctx, s)] = s
                for fut in cf.as_completed(futs):
                    s = futs[fut]
                    done[s.step_id] = fut.result()
        for s in batch:
            if s.step_id in done:
                results.append(done[s.step_id])
                pending.remove(s)
        # a failed mandatory step whose dependants cannot proceed is reported, not patched
        for s in list(pending):
            if any(d in done and not done[d].ok for d in s.depends_on) and not s.optional:
                failed = [d for d in s.depends_on if d in done and not done[d].ok]
                ctx.degrade(f"step {s.step_id} ({s.agent}) not executed: dependency "
                            f"{failed} failed")
                done[s.step_id] = AgentResult(agent=s.agent, step_id=s.step_id, ok=False,
                                              error=f"dependency {failed} failed", degraded=True)
                results.append(done[s.step_id])
                pending.remove(s)

    # 4. report + verify
    ans = ReporterAgent().build(ctx, plan, results)
    _verify(ctx, ans)
    ctx.tracer.emit("run_end", blocked=ans.blocked, n_claims=len(ans.ledger_rows),
                    n_blocks=len(ans.blocks), degraded=len(ans.degraded))
    return ans


def _verify(ctx: RunContext, ans: FinalAnswer) -> None:
    rep = ctx.verifier.verify(ans.blocks)
    ans.verification = {"ok": rep.ok, "summary": rep.summary(),
                        "numeric_coverage": round(rep.numeric_coverage, 4),
                        "n_numeric_tokens": rep.n_numeric_tokens,
                        "n_resolved_tokens": rep.n_resolved_tokens,
                        "n_claims_total": rep.n_claims_total,
                        "n_claims_used": rep.n_claims_used,
                        "violations": [v.model_dump() for v in rep.violations]}
    ctx.tracer.emit("verification", ok=rep.ok, detail=rep.summary())
    if ctx.cfg.get("ablation", {}).get("no_verifier"):
        ctx.tracer.emit("ablation", detail="verifier blocking disabled")
        return
    if not rep.ok and ctx.cfg["verifier"].get("block_on_violation", True):
        ans.blocked = True
        ans.withheld_blocks = list(ans.blocks)
        ans.blocks = [AnswerBlock(
            title="Answer withheld by the claims verifier",
            text=("The assembled answer contained statements the claims ledger could not support, "
                  "so it was not published. This is the intended behaviour: an unsupported number "
                  "is treated as a defect, not as output.\n\n" +
                  "\n".join(f"- **{v.kind}**: {v.detail}" for v in rep.violations[:10])),
            level="warning")] + [b for b in ans.blocks if not b.claim_ids]
