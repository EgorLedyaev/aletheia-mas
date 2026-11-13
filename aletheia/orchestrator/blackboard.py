"""Blackboard (parallel fan-out) orchestration -- the alternative pattern we benchmark against.

No explicit step graph. Every specialist declares the blackboard keys it needs and the keys it
produces; in each round, all agents whose preconditions are satisfied run concurrently. The run
ends when a round adds nothing new. This is more permissive than the supervisor (agents can fire
as soon as data appears) and is measurably faster on some requests, at the cost of weaker control
over tool ordering -- which is exactly the trade-off the evaluation harness quantifies.
"""
from __future__ import annotations

import concurrent.futures as cf
from typing import Any, Dict, List

from ..agents import get_agent
from ..agents.planner import PlannerAgent
from ..agents.reporter import ReporterAgent
from ..agents.safety import SafetyAgent
from ..core.contracts import AgentResult, Intent, PlanStep
from ..core.context import RunContext
from .supervisor import _refusal_answer, _verify

# agent -> (required blackboard keys, produced keys, action, intents that enable it)
SPECS: Dict[str, Dict[str, Any]] = {
    "target_analyst": {"needs": ["targets"], "produces": ["target_card"], "action": "resolve_target",
                       "intents": {"target_brief", "ligand_lookup", "docking", "qsar",
                                   "protein_analysis", "full_campaign", "generate_analogs",
                                   "rank_candidates"}},
    "structure_analyst": {"needs": ["receptor_pdb_path"], "produces": ["pockets"],
                          "action": "analyse_structure", "intents": {"protein_analysis",
                                                                     "full_campaign"}},
    "chemistry_retriever": {"needs": ["target_card"], "produces": ["actives"],
                            "action": "known_actives",
                            "intents": {"ligand_lookup", "qsar", "generate_analogs",
                                        "full_campaign", "rank_candidates"}},
    "property_agent": {"needs": ["molecules"], "produces": ["user_candidates"],
                       "action": "profile_molecules", "intents": {"property_profile"}},
    "molecule_generator": {"needs": ["actives"], "produces": ["candidates"], "action": "generate",
                           "intents": {"generate_analogs", "full_campaign"}},
    "qsar_agent": {"needs": ["actives"], "produces": ["qsar"], "action": "fit_and_predict",
                   "intents": {"qsar", "full_campaign"}},
    "docking_agent": {"needs": ["receptor_pdb_path"], "produces": ["docking"], "action": "dock",
                      "intents": {"docking", "full_campaign"}},
    "ranker": {"needs": ["candidates"], "produces": ["portfolio"], "action": "rank_and_select",
               "intents": {"rank_candidates", "generate_analogs", "full_campaign"}},
    "critic": {"needs": [], "produces": ["critic"], "action": "cross_check", "intents": set()},
}


def run_blackboard(ctx: RunContext) -> Any:
    safety = SafetyAgent()
    decision = safety.review_request(ctx)
    if decision["verdict"] == "REFUSE":
        ctx.tracer.emit("run_end", refused=True)
        return _refusal_answer(ctx, decision)

    plan = PlannerAgent().plan(ctx)
    ctx.note("targets", plan.targets)
    ctx.note("molecules", plan.molecules)
    intents = {i.value for i in plan.intents}
    results: List[AgentResult] = []
    ran: set = set()
    round_no = 0
    while True:
        round_no += 1
        ready = []
        for name, spec in SPECS.items():
            if name in ran or name == "critic":
                continue
            if spec["intents"] and not (spec["intents"] & intents):
                continue
            if all(ctx.blackboard.get(k) for k in spec["needs"]):
                ready.append(name)
        if not ready or ctx.over_budget or round_no > 8:
            break
        ctx.tracer.emit("blackboard_round", n=round_no, agents=ready)
        steps = {name: PlanStep(step_id=f"B{round_no}-{name}", agent=name,
                                action=SPECS[name]["action"],
                                inputs={"targets": plan.targets, "smiles": plan.molecules,
                                        "need_structure": bool({"docking", "protein_analysis",
                                                                "full_campaign"} & intents)})
                 for name in ready}
        if len(ready) == 1:
            name = ready[0]
            results.append(get_agent(name).run(ctx, steps[name]))
            ran.add(name)
        else:
            with cf.ThreadPoolExecutor(max_workers=min(4, len(ready))) as pool:
                futs = {pool.submit(get_agent(n).run, ctx, steps[n]): n for n in ready}
                for fut in cf.as_completed(futs):
                    results.append(fut.result())
                    ran.add(futs[fut])
        # candidates must be profiled before ranking in this pattern too
        if "molecule_generator" in ran and "profiled" not in ran and ctx.blackboard.get("candidates"):
            st = PlanStep(step_id=f"B{round_no}-profile", agent="property_agent",
                          action="profile_candidates", inputs={})
            results.append(get_agent("property_agent").run(ctx, st))
            ran.add("profiled")

    crit = get_agent("critic")
    results.append(crit.run(ctx, PlanStep(step_id="B-critic", agent="critic",
                                          action="cross_check", inputs={})))
    plan.steps = [PlanStep(step_id=f"B-{i+1}", agent=r.agent, action="(blackboard round)",
                           inputs={}, rationale="fired when its blackboard preconditions were met")
                  for i, r in enumerate(results)]
    plan.planner = plan.planner + " / blackboard"
    ans = ReporterAgent().build(ctx, plan, results)
    _verify(ctx, ans)
    ctx.tracer.emit("run_end", blocked=ans.blocked, n_claims=len(ans.ledger_rows),
                    pattern="blackboard", rounds=round_no)
    return ans
