"""Command-line interface.

    python -m aletheia.cli ask "which EGFR structures are available and what binds them?"
    python -m aletheia.cli ask "..." --pattern blackboard --offline --echo
    python -m aletheia.cli tools
    python -m aletheia.cli scenarios --run
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .core.config import load_config


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="aletheia", description="Provenance-enforcing MAS for drug design")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("ask", help="answer one natural-language request")
    a.add_argument("query")
    a.add_argument("--pattern", choices=["supervisor", "blackboard"], default=None)
    a.add_argument("--offline", action="store_true", help="no network, no live LLM: cache only")
    a.add_argument("--echo", action="store_true", help="stream the agent trace")
    a.add_argument("--json", action="store_true", help="print the structured answer as JSON")
    a.add_argument("--no-ledger", action="store_true", help="hide the claims appendix")
    a.add_argument("--config", default=None)

    sub.add_parser("tools", help="list the registered tools")
    sc = sub.add_parser("scenarios", help="list or run the scenario suite")
    sc.add_argument("--run", action="store_true")
    sc.add_argument("--only", default=None, help="comma-separated scenario ids")

    args = p.parse_args(argv)

    if args.cmd == "tools":
        from .core.registry import ToolRegistry
        from .tools import register_all
        cfg = load_config()
        reg = ToolRegistry(cfg)
        register_all(reg, cfg)
        for t in reg.describe():
            print(f"{t['name']:32s} {t['version']:18s} {t['tag']:10s} {t['cost']:9s} "
                  f"{'net' if t['network'] else 'local':6s} {t['license'][:28]:30s} {t['description'][:60]}")
        print(f"\n{len(reg.specs)} tools registered")
        return 0

    if args.cmd == "scenarios":
        from .eval.scenarios import SCENARIOS, run_suite
        if not args.run:
            for s in SCENARIOS:
                print(f"{s['id']:10s} [{s['track']:15s}] {s['query'][:92]}")
            return 0
        only = args.only.split(",") if args.only else None
        run_suite(only=only)
        return 0

    cfg = load_config(args.config)
    if args.offline:
        cfg["llm"]["offline"] = True
        cfg["tools"]["network"] = False
    if args.echo:
        cfg["run"]["echo"] = True
    from .run import run as run_query
    ans = run_query(args.query, config=cfg, pattern=args.pattern)
    if args.json:
        print(json.dumps(ans.model_dump(mode="json"), indent=1, default=str))
    else:
        from .core.render import answer_to_markdown
        print(answer_to_markdown(ans, include_ledger=not args.no_ledger))
    return 1 if ans.blocked else 0


if __name__ == "__main__":
    sys.exit(main())
