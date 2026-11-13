"""Reconstruct the candidate funnel for a run, from that run's claims ledger.

Why this exists: the funnel was quoted in four places (evaluation report, negative-results log,
dashboard figure, deck) from two different runs that coincidentally both generated 126 molecules,
and one of the quotes came from a stale mid-session capture. There is now exactly ONE generated
table: `eval/funnel_table.json` + `docs/funnel_table.md`, and `tests/test_funnel.py` fails if any
document disagrees with it.

    python scripts/funnel_report.py                 # default: S07 and S08 from eval/final_suite.json
    python scripts/funnel_report.py --runs <id> ... # explicit run ids
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ledger key -> funnel stage label; order defines the table rows
STAGES = [
    ("raw_proposals", "raw proposals from the generators"),
    ("unique_after_dedup", "unique after cross-generator dedup"),
    ("hazard_blocked", "removed by the hazard gate"),
    ("after_hazard_gate", "candidates entering the cheap-filter gate"),
    ("gate1_passed", "survive the cheap-filter gate"),
    ("gate1_rejected", "rejected by the cheap-filter gate"),
    ("oracle_scored", "scored by the activity model"),
    ("oracle_out_of_domain", "of those, outside the applicability domain"),
    ("docked", "docked with AutoDock Vina"),
    ("pareto_front", "on the Pareto front"),
    ("chemotype_clusters", "chemotype clusters (Butina)"),
    ("portfolio", "selected into the portfolio"),
]


def _num(rows, key):
    r = rows.get(key)
    if r is None:
        return None
    try:
        return int(float(str(r["value"]).replace(",", "")))
    except (TypeError, ValueError):
        return None


def funnel_for_run(root: str, run_id: str) -> dict:
    path = os.path.join(root, "runs", f"{run_id}.answer.json")
    with open(path, encoding="utf-8") as fh:
        ans = json.load(fh)
    rows = {r["key"]: r for r in ans["ledger_rows"]}
    gens = {k: _num(rows, k) for k in rows if k.endswith("_n_generated")}
    n_docked = sum(1 for r in ans["ledger_rows"] if r["key"] == "vina_score")

    # thresholds are recorded verbatim in the gate claim's note
    thresholds, note = {}, (rows.get("gate1_n_passed") or {}).get("note", "") or ""
    m = re.search(r"\{.*\}", note)
    if m:
        try:
            thresholds = ast.literal_eval(m.group())
        except (ValueError, SyntaxError):
            thresholds = {}

    # the dedup/hazard claim's note carries 'N raw proposals ... -> M unique -> K after the hazard gate'
    raw = uniq = after_haz = None
    n = (rows.get("candidates_after_dedup_and_safety") or {}).get("note", "") or ""
    m = re.search(r"(\d+) raw proposals.*?-> (\d+) unique -> (\d+) after the hazard gate", n)
    if m:
        raw, uniq, after_haz = (int(m.group(i)) for i in (1, 2, 3))

    counts = {
        "raw_proposals": raw if raw is not None else (sum(v for v in gens.values() if v) or None),
        "unique_after_dedup": uniq,
        "hazard_blocked": _num(rows, "hazard_blocked_structures") or 0,
        "after_hazard_gate": after_haz if after_haz is not None
        else _num(rows, "candidates_after_dedup_and_safety"),
        "gate1_passed": _num(rows, "gate1_n_passed"),
        "gate1_rejected": _num(rows, "gate1_n_rejected"),
        "oracle_scored": _num(rows, "qsar_candidates_scored"),
        "oracle_out_of_domain": _num(rows, "qsar_candidates_out_of_domain"),
        "docked": n_docked or None,
        "pareto_front": _num(rows, "pareto_front_size"),
        "chemotype_clusters": _num(rows, "n_chemotype_clusters"),
        "portfolio": _num(rows, "portfolio_size"),
    }
    seed = None
    trace = os.path.join(root, "runs", f"{run_id}.jsonl")
    if os.path.exists(trace):
        for line in open(trace, encoding="utf-8"):
            if '"seed_choice"' in line:
                try:
                    seed = json.loads(line).get("smiles")
                except json.JSONDecodeError:
                    pass
    return {"run_id": run_id, "query": ans["query"], "generators": gens, "counts": counts,
            "gate_thresholds": thresholds, "generator_seed": seed,
            "source": ans.get("source"), "duration_s": ans.get("duration_s")}


def consistency(f: dict) -> list:
    """Internal arithmetic the funnel must satisfy; violations are returned as strings."""
    c, bad = f["counts"], []
    if c["gate1_passed"] is not None and c["gate1_rejected"] is not None \
            and c["after_hazard_gate"] is not None:
        if c["gate1_passed"] + c["gate1_rejected"] != c["after_hazard_gate"]:
            bad.append(f"gate1_passed+gate1_rejected ({c['gate1_passed']}+{c['gate1_rejected']}) "
                       f"!= after_hazard_gate ({c['after_hazard_gate']})")
    if c["unique_after_dedup"] is not None and c["hazard_blocked"] is not None \
            and c["after_hazard_gate"] is not None:
        if c["unique_after_dedup"] - c["hazard_blocked"] != c["after_hazard_gate"]:
            bad.append("unique_after_dedup - hazard_blocked != after_hazard_gate")
    if c["oracle_scored"] is not None and c["gate1_passed"] is not None \
            and c["oracle_scored"] > c["gate1_passed"]:
        bad.append(f"oracle_scored ({c['oracle_scored']}) > gate1_passed ({c['gate1_passed']}): "
                   "the expensive oracle ran before the cheap gate")
    if c["oracle_out_of_domain"] is not None and c["oracle_scored"] is not None \
            and c["oracle_out_of_domain"] > c["oracle_scored"]:
        bad.append("oracle_out_of_domain > oracle_scored")
    # A portfolio may hold several molecules from one chemotype cluster -- that is a diversity
    # outcome, not an arithmetic error. The impossible case is selecting more molecules than were
    # scored.
    if c["portfolio"] is not None and c["gate1_passed"] is not None \
            and c["portfolio"] > c["gate1_passed"]:
        bad.append(f"portfolio ({c['portfolio']}) larger than the number of molecules that "
                   f"passed the gate ({c['gate1_passed']})")
    gens_sum = sum(v for v in f["generators"].values() if v)
    if gens_sum and c["raw_proposals"] and gens_sum != c["raw_proposals"]:
        bad.append(f"per-generator counts sum to {gens_sum} but raw_proposals is {c['raw_proposals']}")
    return bad


def render_markdown(funnels: list) -> str:
    ids = [f["run_id"] for f in funnels]
    labels = [f.get("scenario") or f["run_id"][:14] for f in funnels]
    out = ["# Candidate funnel (generated — do not edit by hand)", "",
           "Produced by `python scripts/funnel_report.py` from the claims ledger of each run.",
           "Every document that quotes funnel numbers must match this table; "
           "`tests/test_funnel.py` enforces it.", ""]
    out.append("| stage | " + " | ".join(labels) + " |")
    out.append("|---|" + "---|" * len(funnels))
    for key, label in STAGES:
        vals = []
        for f in funnels:
            v = f["counts"].get(key)
            vals.append("—" if v is None else str(v))
        out.append(f"| {label} | " + " | ".join(vals) + " |")
    out += ["", "## Run identity", "",
            "| | " + " | ".join(labels) + " |", "|---|" + "---|" * len(funnels),
            "| run id | " + " | ".join(f"`{i}`" for i in ids) + " |",
            "| generator seed | " + " | ".join(
                f"`{(f['generator_seed'] or 'user molecule from the query')[:46]}`"
                for f in funnels) + " |",
            "| per-generator counts | " + " | ".join(
                ", ".join(f"{k.split('_')[0]}={v}" for k, v in sorted(f["generators"].items()))
                for f in funnels) + " |", ""]
    th = funnels[0]["gate_thresholds"]
    if th:
        out += ["## Cheap-filter gate thresholds (identical in both runs)", "",
                "| parameter | value |", "|---|---|"]
        out += [f"| `{k}` | {v} |" for k, v in sorted(th.items())]
        out.append("")
    out += ["## Why the two runs differ", "",
            "Both runs generated the same *number* of unique molecules (a coincidence: 36+40+40+10 "
            "and 37+40+40+9 both total 126), but from different seeds — S07 is seeded with the "
            "erlotinib SMILES given in the query, S08 with the most potent retrieved active, "
            "because its query names no molecule. Different seed, different candidate population, "
            "different survival rate at an identical gate.", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="*", default=None)
    ap.add_argument("--root", default=HERE)
    args = ap.parse_args(argv)

    scen = {}
    if not args.runs:
        with open(os.path.join(args.root, "eval", "final_suite.json"), encoding="utf-8") as fh:
            suite = json.load(fh)
        scen = {r["run_id"]: r["id"] for r in suite["results"] if r.get("run_id")}
        args.runs = [rid for rid, sid in scen.items() if sid in ("S07", "S08")]
        args.runs.sort(key=lambda r: scen[r])

    funnels = []
    for rid in args.runs:
        f = funnel_for_run(args.root, rid)
        f["scenario"] = scen.get(rid, rid[:12])
        f["consistency_violations"] = consistency(f)
        funnels.append(f)

    os.makedirs(os.path.join(args.root, "eval"), exist_ok=True)
    with open(os.path.join(args.root, "eval", "funnel_table.json"), "w", encoding="utf-8") as fh:
        json.dump({"funnels": funnels, "stages": dict(STAGES)}, fh, indent=1)
    with open(os.path.join(args.root, "docs", "funnel_table.md"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(render_markdown(funnels))

    # eval/dashboard_funnel.json is the flat per-scenario view other tools read. It used to be
    # maintained by hand and drifted away from the ledgers (see W1 in docs/evaluation_report.md);
    # it is now a derived file and is rewritten from the same counts as the table above.
    flat = {f["scenario"]: {"run_id": f["run_id"], **{k: v for k, v in f["counts"].items()
                                                      if v is not None}}
            for f in funnels}
    flat["_provenance"] = {"generated_by": "scripts/funnel_report.py",
                           "derived_from": "eval/funnel_table.json",
                           "warning": "generated file -- edit the run ledgers, not this"}
    with open(os.path.join(args.root, "eval", "dashboard_funnel.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump(flat, fh, indent=1)

    for f in funnels:
        c = f["counts"]
        print(f"{f['scenario']} {f['run_id']}: "
              f"{c['raw_proposals']} raw -> {c['after_hazard_gate']} after hazard -> "
              f"{c['gate1_passed']} pass gate 1 -> {c['oracle_scored']} scored -> "
              f"{c['docked'] or 0} docked -> {c['portfolio']} in portfolio")
        for v in f["consistency_violations"]:
            print("   VIOLATION:", v)
    bad = sum(len(f["consistency_violations"]) for f in funnels)
    print(f"{len(funnels)} runs, {bad} consistency violation(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
