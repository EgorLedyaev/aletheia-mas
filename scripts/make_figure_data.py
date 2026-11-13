"""Rebuild eval/figure_data_s07.json from a finished run's claims ledger.

Figure inputs are derived from run logs, never carried forward by hand: an earlier side file
survived a code change and kept two superseded numbers (G2 novelty 0.00 instead of 0.075, and a
cheap-gate survival of 5 instead of 43) into the documents.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build(root: str, run_id: str) -> dict:
    with open(os.path.join(root, "runs", f"{run_id}.answer.json"), encoding="utf-8") as fh:
        ans = json.load(fh)
    rows = {r["key"]: r for r in ans["ledger_rows"]}
    gens: dict = {}
    for key, row in rows.items():
        for suffix in ("n_generated", "frac_novel", "mean_max_similarity"):
            m = re.match(rf"(G\d_\w+?)_{suffix}$", key)
            if m:
                field = "n" if suffix == "n_generated" else suffix
                gens.setdefault(m.group(1), {})[field] = (
                    int(float(row["value"])) if field == "n" else float(row["value"]))
    missing = {g: [k for k in ("n", "frac_novel", "mean_max_similarity") if k not in v]
               for g, v in gens.items()}
    missing = {g: m for g, m in missing.items() if m}
    return {"run_id": run_id, "query": ans["query"], "generator_stats": gens,
            "missing_fields": missing,
            "candidates": [c for c in ans.get("candidates", [])],
            "source": ans.get("source")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None)
    ap.add_argument("--root", default=HERE)
    ap.add_argument("--out", default="eval/figure_data_s07.json")
    args = ap.parse_args(argv)
    if not args.run:
        # Pick the generation run that exercised the MOST generators, preferring S07. A run made
        # while the chemistry retriever was unavailable exercises only the three generators that
        # work from the user's seed, and a per-generator comparison drawn from it would silently
        # omit BRICS recombination while the surrounding prose still discussed it.
        with open(os.path.join(args.root, "eval", "final_suite.json"), encoding="utf-8") as fh:
            suite = json.load(fh)
        candidates = [r for r in suite["results"] if r["id"] in ("S07", "S08")]
        scored = []
        for r in candidates:
            try:
                d = build(args.root, r["run_id"])
            except (OSError, KeyError, json.JSONDecodeError):
                continue
            scored.append((len(d["generator_stats"]), r["id"] == "S07", r["run_id"]))
        if not scored:
            raise SystemExit("no usable generation run in eval/final_suite.json")
        scored.sort(reverse=True)
        args.run = scored[0][2]
    data = build(args.root, args.run)
    data["n_generators_in_run"] = len(data["generator_stats"])
    data["generators_absent"] = sorted(
        {"G1_rule_decorate", "G2_brics_recombine", "G3_selfies_mutate", "G4_llm_edits"}
        - set(data["generator_stats"]))
    with open(os.path.join(args.root, args.out), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    print(f"{args.out} <- run {args.run}")
    for g, v in sorted(data["generator_stats"].items()):
        print(f"  {g:22s} n={v.get('n')} frac_novel={v.get('frac_novel')} "
              f"mean_max_sim={v.get('mean_max_similarity')}")
    if data["missing_fields"]:
        print("  MISSING:", data["missing_fields"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
