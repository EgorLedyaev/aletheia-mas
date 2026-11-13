"""Evaluation harness: orchestration comparison, ablations, baselines.

    python -m eval.harness --quick          # cached scenarios only, both patterns + ablations
    python -m eval.harness --full           # includes the slow campaign and live baselines

Outputs
    eval/harness_report.json      every measurement
    docs/evaluation_report.md     the written report with the comparison tables
    figures/*.png                 the dashboard figures (produced by eval/figures.py)
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aletheia.core.config import load_config                        # noqa: E402
from aletheia.eval.scenarios import SCENARIOS, run_suite            # noqa: E402

BASELINE_QUERIES = ["S01", "S04", "S05"]     # one protein, one retrieval, one structure-based


def _cfg(**ablation: Any) -> Dict[str, Any]:
    cfg = load_config()
    cfg["ablation"] = {**cfg.get("ablation", {}), **ablation}
    cfg["run"]["echo"] = False
    return cfg


def summarise(suite: Dict[str, Any]) -> Dict[str, Any]:
    rs = suite["results"]
    covs = [r.get("coverage") for r in rs if isinstance(r.get("coverage"), (int, float))]
    return {"n": suite["n"], "n_passed": suite["n_passed"],
            "pass_rate": round(suite["n_passed"] / suite["n"], 4) if suite["n"] else None,
            "total_duration_s": suite["total_duration_s"],
            "median_duration_s": round(statistics.median([r["duration_s"] for r in rs]), 2) if rs else None,
            "mean_ledger_coverage": round(statistics.fmean(covs), 4) if covs else None,
            "n_blocked": sum(1 for r in rs if r.get("blocked")),
            "n_refused": sum(1 for r in rs if r.get("refused")),
            "total_llm_calls": sum(r.get("llm_calls") or 0 for r in rs),
            "total_tool_calls": sum(r.get("n_tool_calls") or 0 for r in rs),
            "failures": {r["id"]: r["failures"] for r in rs if not r["passed"]}}


def run_harness(quick: bool = True, out_dir: str = "eval") -> Dict[str, Any]:
    t0 = time.time()
    report: Dict[str, Any] = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "quick": quick}
    skip_slow = quick

    # 1. orchestration patterns, identical scenarios and configuration
    patterns = {}
    for pattern in ("supervisor", "blackboard"):
        suite = run_suite(pattern=pattern, config=_cfg(), skip_slow=skip_slow,
                          write_cards_to="docs/scenarios" if pattern == "supervisor" else None)
        patterns[pattern] = {"summary": summarise(suite), "results": suite["results"]}
    report["orchestration"] = patterns

    # 2. ablations, all against the supervisor pattern
    ablations = {}
    for name, flags, only in [
        ("no_critic", {"no_critic": True}, None),
        ("single_generator", {"single_generator": True}, ["S07"]),
        ("no_guardrail", {"no_guardrail": True}, ["S09", "S10"]),
        ("no_verifier", {"no_verifier": True}, None),
    ]:
        suite = run_suite(pattern="supervisor", config=_cfg(**flags), skip_slow=True,
                          only=only, write_cards_to=None,
                          out_dir=os.path.join(out_dir, "ablations"))
        ablations[name] = {"flags": flags, "scenarios": only or "all (fast)",
                           "summary": summarise(suite), "results": suite["results"]}
    report["ablations"] = ablations

    # 3. baselines on a subset
    from aletheia.eval.baselines import plain_llm, single_agent
    baselines: Dict[str, Any] = {"B1_plain_llm": [], "B2_single_agent": []}
    for sid in BASELINE_QUERIES:
        scn = next(s for s in SCENARIOS if s["id"] == sid)
        try:
            b1 = plain_llm(scn["query"], _cfg())
            b1["scenario"] = sid
            baselines["B1_plain_llm"].append(b1)
        except Exception as exc:
            baselines["B1_plain_llm"].append({"scenario": sid, "error": f"{type(exc).__name__}: {exc}"})
        try:
            b2 = single_agent(scn["query"], _cfg())
            b2["scenario"] = sid
            baselines["B2_single_agent"].append(b2)
        except Exception as exc:
            baselines["B2_single_agent"].append({"scenario": sid, "error": f"{type(exc).__name__}: {exc}"})
    for k, rows in baselines.items():
        ok = [r for r in rows if not r.get("error")]
        baselines[k] = {
            "runs": rows,
            "n": len(ok),
            "mean_identifiers_found": round(statistics.fmean([r["identifiers_found"] for r in ok]), 2) if ok else None,
            "n_nonexistent_identifiers": sum(r["n_nonexistent"] for r in ok),
            "mean_numeric_tokens": round(statistics.fmean([r["n_numeric_tokens"] for r in ok]), 2) if ok else None,
            "mean_duration_s": round(statistics.fmean([r["duration_s"] for r in ok]), 2) if ok else None,
            "mean_tool_calls": round(statistics.fmean([r["n_tool_calls"] for r in ok]), 2) if ok else None,
        }
    report["baselines"] = baselines

    # 4. the MAS comparison numbers on the same subset
    mas_rows = [r for r in patterns["supervisor"]["results"] if r["id"] in BASELINE_QUERIES]
    report["mas_on_baseline_subset"] = {
        "n": len(mas_rows),
        "pass_rate": round(sum(1 for r in mas_rows if r["passed"]) / len(mas_rows), 4) if mas_rows else None,
        "mean_duration_s": round(statistics.fmean([r["duration_s"] for r in mas_rows]), 2) if mas_rows else None,
        "mean_tool_calls": round(statistics.fmean([r["n_tool_calls"] for r in mas_rows]), 2) if mas_rows else None,
        "mean_ledger_coverage": round(statistics.fmean(
            [r["coverage"] for r in mas_rows if isinstance(r.get("coverage"), (int, float))]), 4)
        if mas_rows else None,
    }

    # 5. docking validation, if it has been run
    dv = os.path.join("eval", "docking_validation.json")
    if os.path.exists(dv):
        with open(dv, encoding="utf-8") as fh:
            d = json.load(fh)
        report["docking_validation"] = {k: v for k, v in d.items() if k != "rows"}

    report["duration_s"] = round(time.time() - t0, 1)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "harness_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    print(json.dumps({"orchestration": {k: v["summary"] for k, v in patterns.items()},
                      "ablations": {k: v["summary"] for k, v in ablations.items()}},
                     indent=1, default=str))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="include the slow campaign scenario")
    ap.add_argument("--quick", action="store_true", default=True)
    args = ap.parse_args(argv)
    run_harness(quick=not args.full)
    return 0


if __name__ == "__main__":
    sys.exit(main())
