"""Regenerate every generated artefact from the run logs, in dependency order.

Nothing in docs/ or figures/ is written by hand; this script is the only way they are produced,
so "the documents disagree with the runs" is a build failure rather than a review finding.

    python scripts/regenerate_all.py            # all steps
    python scripts/regenerate_all.py --list     # show the order
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STEPS = [
    ("funnel_report.py", "funnel table from the claims ledgers"),
    ("sync_suite_table.py", "scenario table in docs/evaluation_report.md"),
    ("sync_funnel_docs.py", "rewrite marked funnel numbers in docs/ from that table"),
    ("make_figure_data.py", "generator statistics from the S07 ledger"),
    ("make_generator_figure.py", "figures/generator_comparison.png"),
    ("docking_report.py", "docking validation table + figures/docking_benchmark.png"),
    ("make_calibration_figure.py", "figures/calibration.png"),
    ("make_baseline_figure.py", "figures/baseline_study.png"),
    ("make_dashboard.py", "figures/eval_dashboard.png"),
    ("make_portfolio_figure.py", "figures/deck/portfolio_molecules.png"),
    ("make_chemspace_figure.py", "figures/deck/chemical_space.png"),
    ("make_cross_target_figure.py", "figures/deck/cross_target_benchmark.png + "
                                    "docs/cross_target_summary.md (reuses eval/cross_target.json; "
                                    "pass --force to refit the three activity models)"),
    ("make_provenance_figure.py", "figures/deck/provenance_architecture.png"),
    ("eval_synthesis.py", "docs/synthesis_feasibility.md"),
    ("deck_stats.py", "eval/deck_stats.json: the counts the deck may state"),
    ("make_deck.py", "docs/deck.pdf + figures/deck/slide_*.png"),
    ("make_manifest.py", "registry/manifest.json (file hashes)"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--skip", default="", help="comma-separated script names to skip")
    args = ap.parse_args()
    if args.list:
        for s, why in STEPS:
            print(f"{s:28s} {why}")
        return 0
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    failures = []
    for script, why in STEPS:
        if script in skip:
            print(f"-- skip {script}")
            continue
        path = os.path.join(HERE, "scripts", script)
        if not os.path.exists(path):
            print(f"-- missing {script}")
            continue
        t0 = time.time()
        env = dict(os.environ, PYTHONPATH=HERE)
        r = subprocess.run([sys.executable, path], cwd=HERE, env=env,
                           capture_output=True, text=True)
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        print(f"[{'ok ' if r.returncode == 0 else 'FAIL'}] {script:28s} "
              f"{time.time() - t0:5.1f}s  {tail[-1][:90] if tail else ''}")
        if r.returncode != 0:
            failures.append(script)
            print((r.stderr or "")[-600:])
    if failures:
        print(f"\n{len(failures)} step(s) failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("\nall generated artefacts rebuilt from run logs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
