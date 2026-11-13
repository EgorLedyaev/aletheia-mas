"""Collect the counts the deck is allowed to state, from measured files only.

Writes eval/deck_stats.json. make_deck.py substitutes {{token}} placeholders from it and refuses
to render if a placeholder has no measured value -- so a slide cannot claim a pass rate that no
run produced. This exists because a reviewer caught the deck asserting "13/13" while the suite
had not finished.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    stats = {}
    suite_path = os.path.join(HERE, "eval", "final_suite.json")
    if os.path.exists(suite_path):
        with open(suite_path, encoding="utf-8") as fh:
            s = json.load(fh)
        stats["scenarios_total"] = s.get("n")
        stats["scenarios_passed"] = s.get("n_passed")
        stats["scenario_ids"] = [r.get("id") for r in s.get("results", [])]
        stats["suite_duration_s"] = s.get("total_duration_s")
    rt_path = os.path.join(HERE, "eval", "redteam_results.json")
    if os.path.exists(rt_path):
        with open(rt_path, encoding="utf-8") as fh:
            r = json.load(fh)
        stats["probes_total"] = r.get("n")
        stats["probes_passed"] = r.get("n_passed")
    out = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "--no-header"],
                         cwd=HERE, capture_output=True, text=True,
                         env=dict(os.environ, PYTHONPATH=HERE))
    m = re.search(r"(\d+) passed", out.stdout) or re.search(r"^(\.+)\s*\[100%\]", out.stdout, re.M)
    if m:
        stats["tests_passed"] = int(m.group(1)) if m.group(1).isdigit() else len(m.group(1))
    stats["tests_exit_code"] = out.returncode
    with open(os.path.join(HERE, "eval", "deck_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=1)
    print(f"scenarios {stats.get('scenarios_passed')}/{stats.get('scenarios_total')}, "
          f"tests {stats.get('tests_passed')}, "
          f"probes {stats.get('probes_passed')}/{stats.get('probes_total')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
