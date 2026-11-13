"""RunContext -- the shared state every agent receives (and the only thing they share)."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from .config import load_config
from .ledger import AnswerVerifier, ClaimsLedger
from .llm import LLMClient
from .provenance import new_run_id
from .registry import ToolRegistry
from .trace import Tracer


class RunContext:
    def __init__(self, query: str, config: Optional[Dict[str, Any]] = None,
                 run_id: Optional[str] = None):
        self.cfg = config or load_config()
        self.query = query
        self.run_id = run_id or new_run_id()
        self.started_at = time.time()
        self.tracer = Tracer(self.run_id, run_dir=self.cfg["run"]["run_dir"],
                             echo=bool(self.cfg["run"].get("echo")))
        self.ledger = ClaimsLedger(self.run_id)
        self.tools = ToolRegistry(self.cfg, tracer=self.tracer)
        self.llm = LLMClient(self.cfg, tracer=self.tracer)
        self.verifier = AnswerVerifier(
            self.ledger,
            strict_citation=bool(self.cfg["verifier"].get("strict_citation", True)),
            allow_global_pool=bool(self.cfg["verifier"].get("allow_global_pool", True)))
        self.blackboard: Dict[str, Any] = {}      # agent-visible shared facts
        self._lock = threading.Lock()
        self.degraded: List[str] = []             # human-readable degradation notes
        self.safety: Dict[str, Any] = {}
        self.budget_s = float(self.cfg["orchestrator"].get("budget_s", 900))
        from ..tools import register_all
        register_all(self.tools, self.cfg)
        self.tracer.emit("run_start", query=query, run_id=self.run_id,
                         llm_backend=self.llm.backend_name, tools=len(self.tools.specs),
                         pattern=self.cfg["orchestrator"].get("pattern"))

    # -- helpers -------------------------------------------------------------
    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at

    @property
    def over_budget(self) -> bool:
        return self.elapsed > self.budget_s

    def degrade(self, note: str) -> None:
        """Record an honest degradation: a tool failed or data was missing. Never fill the gap."""
        if note not in self.degraded:
            self.degraded.append(note)
        self.tracer.emit("degraded", detail=note)

    def note(self, key: str, value: Any) -> None:
        with self._lock:
            self.blackboard[key] = value

    def source_mix(self) -> str:
        cached = sum(1 for c in self.tools.history if c.cached)
        return "cached" if cached and cached == len(self.tools.history) else (
            "mixed" if cached else "live")
