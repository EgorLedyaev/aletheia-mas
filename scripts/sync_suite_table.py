"""Rewrite the scenario table in docs/evaluation_report.md from eval/final_suite.json.

The table used to be maintained by hand and drifted: it still listed 12 scenarios, the wrong
title for S05 and wall times from an older run after S05b had been added.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START = "<!--suite-table-start-->"
END = "<!--suite-table-end-->"


def main() -> int:
    with open(os.path.join(HERE, "eval", "final_suite.json"), encoding="utf-8") as fh:
        suite = json.load(fh)
    lines = ["| id | track | scenario | result | wall time | claims | ledger coverage |",
             "|---|---|---|---|---|---|---|"]
    for r in suite["results"]:
        cov = r.get("coverage", r.get("ledger_coverage"))
        cov_txt = "n/a" if cov is None else f"{cov * 100:.0f}%"
        lines.append(f"| {r['id']} | {r.get('track', '')} | {r.get('title', '')} | "
                     f"{'PASS' if r['passed'] else 'FAIL'} | {r['duration_s']:.1f} s | "
                     f"{r.get('n_claims', '')} | {cov_txt} |")
    table = "\n".join(lines)
    path = os.path.join(HERE, "docs", "evaluation_report.md")
    text = open(path, encoding="utf-8").read()
    if START not in text or END not in text:
        print(f"markers {START}/{END} not found in evaluation_report.md", file=sys.stderr)
        return 1
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    new = (f"{head}{START}\n{table}\n\n{suite['n_passed']}/{suite['n']} scenarios passed in "
           f"{suite['total_duration_s']} s (supervisor pattern, offline replay).\n{END}{tail}")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new)
    print(f"scenario table synchronised: {suite['n_passed']}/{suite['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
