"""Rewrite every funnel number in docs/ that carries a <!--funnel:SCEN.key--> marker.

The marker is the binding between a sentence and a generated value. This script makes the
documents follow the table instead of the other way round, so a re-run that changes the funnel
cannot leave prose behind. tests/test_funnel.py then verifies the result.
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKER = re.compile(r"(\d+(?:\.\d+)?)([\s*`]{0,6})<!--funnel:([A-Za-z0-9]+)\.([a-z0-9_]+)-->")
DOCS = ["docs/evaluation_report.md", "docs/negative_results.md", "docs/deck.md"]


def main() -> int:
    with open(os.path.join(HERE, "eval", "funnel_table.json"), encoding="utf-8") as fh:
        table = json.load(fh)
    by = {f["scenario"]: f["counts"] for f in table["funnels"]}
    changed = []
    for rel in DOCS:
        path = os.path.join(HERE, rel)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()

        def repl(m):
            old, gap, scen, key = m.groups()
            want = by.get(scen, {}).get(key)
            if want is None:
                return m.group(0)
            if str(want) != old:
                changed.append(f"{rel}: {scen}.{key} {old} -> {want}")
            return f"{want}{gap}<!--funnel:{scen}.{key}-->"

        new = MARKER.sub(repl, text)
        if new != text:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new)
    for c in changed:
        print(" ", c)
    print(f"{len(changed)} funnel value(s) synchronised from eval/funnel_table.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
