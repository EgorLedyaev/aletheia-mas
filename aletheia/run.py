"""Top-level entry point: `aletheia.run(query)`."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from .core.config import load_config
from .core.context import RunContext
from .core.contracts import FinalAnswer


def run(query: str, config: Optional[Dict[str, Any]] = None, pattern: Optional[str] = None,
        save: bool = True, **overrides: Any) -> FinalAnswer:
    cfg = config or load_config(**overrides)
    if pattern:
        cfg["orchestrator"]["pattern"] = pattern
    ctx = RunContext(query, cfg)
    from .orchestrator import PATTERNS
    fn = PATTERNS.get(cfg["orchestrator"]["pattern"], PATTERNS["supervisor"])
    ans = fn(ctx)
    ans.started_at = ctx.tracer.events[0]["ts"] if ctx.tracer.events else None
    if save:
        os.makedirs(cfg["run"]["run_dir"], exist_ok=True)
        with open(os.path.join(cfg["run"]["run_dir"], f"{ctx.run_id}.answer.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(ans.model_dump(mode="json"), fh, indent=1, default=str)
        with open(os.path.join(cfg["run"]["run_dir"], f"{ctx.run_id}.answer.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(ans.markdown())
    return ans
