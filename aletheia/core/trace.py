"""Run tracing: one JSONL file per run, plus in-memory events for the UI and the harness."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from .provenance import utcnow


class Tracer:
    def __init__(self, run_id: str, run_dir: str = "runs", echo: bool = False):
        self.run_id = run_id
        self.events: List[Dict[str, Any]] = []
        os.makedirs(run_dir, exist_ok=True)
        self.path = os.path.join(run_dir, f"{run_id}.jsonl")
        self.echo = echo
        self._t0 = time.time()

    def emit(self, kind: str, **payload: Any) -> Dict[str, Any]:
        ev = {"ts": utcnow(), "t_rel": round(time.time() - self._t0, 3),
              "run_id": self.run_id, "kind": kind, **payload}
        self.events.append(ev)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, default=str) + "\n")
            fh.flush()
        if self.echo:
            print(f"[{ev['t_rel']:7.2f}s] {kind}: " +
                  " ".join(f"{k}={v}" for k, v in payload.items() if k in
                           ("agent", "tool", "step_id", "ok", "cached", "n", "detail", "backend")))
        return ev

    def of_kind(self, kind: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e["kind"] == kind]

    def tool_sequence(self) -> List[str]:
        return [e["tool"] for e in self.events if e["kind"] == "tool_call"]

    def agent_sequence(self) -> List[str]:
        return [e["agent"] for e in self.events if e["kind"] == "agent_start"]
