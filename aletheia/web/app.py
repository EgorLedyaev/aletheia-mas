"""Minimal web UI: a chat box, a live agent trace, and a claims-ledger panel.

    python -m uvicorn aletheia.web.app:app --host 127.0.0.1 --port 8000

Deliberately dependency-light (FastAPI + one HTML file, no build step) so it starts on a venue
laptop with no network. The point of the UI is not styling: it is that the provenance badges and
the claims ledger are visible next to the answer, so a reviewer can click from a number to the
tool run that produced it.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from ..core.config import load_config
from ..core.render import answer_to_markdown

HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Aletheia", description="Provenance-enforcing MAS for drug design")


class AskRequest(BaseModel):
    query: str
    pattern: Optional[str] = None
    offline: bool = False


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    with open(os.path.join(HERE, "templates", "index.html"), encoding="utf-8") as fh:
        return fh.read()


@app.get("/api/tools")
def tools() -> JSONResponse:
    from ..core.registry import ToolRegistry
    from ..tools import register_all
    cfg = load_config()
    reg = ToolRegistry(cfg)
    register_all(reg, cfg)
    return JSONResponse({"n": len(reg.specs), "tools": reg.describe()})


@app.get("/api/scenarios")
def scenarios() -> JSONResponse:
    from ..eval.scenarios import SCENARIOS
    return JSONResponse({"scenarios": [{k: s[k] for k in ("id", "track", "title", "query")}
                                       for s in SCENARIOS]})


@app.post("/api/ask")
def ask(req: AskRequest) -> JSONResponse:
    from ..run import run as run_query
    cfg = load_config()
    if req.offline:
        cfg["llm"]["offline"] = True
        cfg["tools"]["network"] = False
    ans = run_query(req.query, config=cfg, pattern=req.pattern)
    trace_path = os.path.join(cfg["run"]["run_dir"], f"{ans.run_id}.jsonl")
    trace: List[Dict[str, Any]] = []
    if os.path.exists(trace_path):
        trace = [json.loads(l) for l in open(trace_path, encoding="utf-8")]
    return JSONResponse({
        "run_id": ans.run_id,
        "blocked": ans.blocked,
        "markdown": answer_to_markdown(ans),
        "blocks": [b.model_dump() for b in ans.blocks],
        "ledger": ans.ledger_rows,
        "verification": ans.verification,
        "safety": ans.safety,
        "degraded": ans.degraded,
        "candidates": [c.model_dump() for c in ans.candidates[:20]],
        "cost": ans.cost,
        "source": ans.source,
        "duration_s": ans.duration_s,
        "plan": ans.plan.model_dump(mode="json") if ans.plan else None,
        "trace": [{"t": e.get("t_rel"), "kind": e.get("kind"),
                   "agent": e.get("agent"), "tool": e.get("tool"),
                   "ok": e.get("ok"), "cached": e.get("cached"),
                   "detail": e.get("detail") or e.get("purpose") or e.get("verdict") or ""}
                  for e in trace],
    })
