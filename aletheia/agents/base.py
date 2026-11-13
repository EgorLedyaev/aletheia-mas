"""Agent base class and the agent registry."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..core.contracts import AgentResult, PlanStep
from ..core.context import RunContext
from ..core.provenance import Evidence

AGENT_REGISTRY: Dict[str, "Agent"] = {}


class Agent:
    """Base agent. Subclasses implement `act` and declare the tools they may use."""

    name: str = "agent"
    description: str = ""
    tools: List[str] = []

    def __init_subclass__(cls, **kw: Any):
        super().__init_subclass__(**kw)
        if getattr(cls, "name", None) and cls.name != "agent":
            AGENT_REGISTRY[cls.name] = cls()

    # -- helpers -------------------------------------------------------------
    def ev(self, ctx: RunContext, tag: str, key: str, value: Any, *, call: Any = None,
           **kw: Any) -> Evidence:
        """Register one Evidence record, inheriting tool identity from a ToolResult."""
        if call is not None:
            kw.setdefault("tool", call.tool)
            kw.setdefault("tool_version", call.version)
            kw.setdefault("params_hash", call.params_hash)
            kw.setdefault("call_id", call.call_id)
        return ctx.ledger.register(tag=tag, key=key, value=value, **kw)

    def fail(self, step: PlanStep, msg: str, t0: float) -> AgentResult:
        return AgentResult(agent=self.name, step_id=step.step_id, ok=False, error=msg,
                           duration_s=round(time.time() - t0, 3))

    # -- api -----------------------------------------------------------------
    def act(self, ctx: RunContext, step: PlanStep) -> AgentResult:    # pragma: no cover
        raise NotImplementedError

    def run(self, ctx: RunContext, step: PlanStep) -> AgentResult:
        t0 = time.time()
        ctx.tracer.emit("agent_start", agent=self.name, step_id=step.step_id, action=step.action)
        try:
            res = self.act(ctx, step)
        except Exception as exc:
            res = AgentResult(agent=self.name, step_id=step.step_id, ok=False,
                              error=f"{type(exc).__name__}: {exc}"[:400])
            ctx.degrade(f"{self.name} failed on {step.action}: {type(exc).__name__}")
        res.duration_s = round(time.time() - t0, 3)
        ctx.tracer.emit("agent_end", agent=self.name, step_id=step.step_id, ok=res.ok,
                        n_evidence=len(res.evidence), degraded=res.degraded,
                        duration_s=res.duration_s, error=res.error)
        return res


def get_agent(name: str) -> Optional[Agent]:
    return AGENT_REGISTRY.get(name)


def all_agents() -> Dict[str, Agent]:
    return dict(AGENT_REGISTRY)
