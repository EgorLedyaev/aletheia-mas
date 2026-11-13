"""Rendering of a FinalAnswer to Markdown, with provenance badges and a claims appendix."""
from __future__ import annotations

from typing import Any, Dict, List

TAG_ICON = {"COMPUTED": "[COMPUTED]", "PREDICTED": "[PREDICTED]", "RETRIEVED": "[RETRIEVED]",
            "HYPOTHESIS": "[HYPOTHESIS]"}


def answer_to_markdown(ans: Any, include_ledger: bool = True, max_candidates: int = 12) -> str:
    out: List[str] = []
    out.append(f"# Aletheia answer\n")
    out.append(f"**Request:** {ans.query}\n")
    meta = [f"run `{ans.run_id}`", f"source `{ans.source}`", f"{ans.duration_s:.1f}s"]
    if ans.plan:
        meta.append("planner `" + ans.plan.planner + "`")
        meta.append("intents " + ", ".join(i.value if hasattr(i, "value") else str(i)
                                           for i in ans.plan.intents))
    out.append("*" + " · ".join(meta) + "*\n")

    if ans.blocked:
        out.append("> **Answer blocked.** The claims verifier refused to publish this answer.\n")

    for b in ans.blocks:
        prefix = {"warning": "> ", "note": "> ", "section": ""}.get(b.level, "")
        out.append(f"## {b.title}\n")
        out.append("\n".join(prefix + ln for ln in b.text.splitlines()) + "\n")
        if b.claim_ids:
            out.append(f"<sub>claims: {', '.join(b.claim_ids)}</sub>\n")

    if ans.candidates:
        out.append("## Candidates\n")
        keys = ["rank", "cand_id", "origin", "MolWt", "cLogP", "TPSA", "QED", "SAscore",
                "vina_score", "qsar_pchembl", "n_structural_alerts"]
        head = [k for k in keys]
        out.append("| " + " | ".join(head) + " | SMILES |")
        out.append("|" + "---|" * (len(head) + 1))
        for c in ans.candidates[:max_candidates]:
            row = []
            for k in head:
                if k == "rank":
                    row.append(str(c.rank if c.rank is not None else ""))
                elif k == "cand_id":
                    row.append(c.cand_id)
                elif k == "origin":
                    row.append(c.origin)
                elif k in c.scores:
                    row.append(f"{c.scores[k]:.3f}")
                else:
                    v = c.properties.get(k)
                    row.append("" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v)))
            out.append("| " + " | ".join(row) + f" | `{c.smiles}` |")
        out.append("")

    if ans.degraded:
        out.append("## Degradations (reported, not filled in)\n")
        for d in ans.degraded:
            out.append(f"- {d}")
        out.append("")

    if ans.safety:
        out.append("## Safety\n")
        out.append(f"- verdict **{ans.safety.get('verdict')}** ({ans.safety.get('category')}): "
                   f"{ans.safety.get('reason')}")
        out.append("")

    if ans.verification:
        v = ans.verification
        out.append("## Verification\n")
        out.append(f"- claims ledger: {v.get('summary')}")
        if v.get("violations"):
            for viol in v["violations"][:10]:
                out.append(f"  - **{viol['kind']}**: {viol['detail']}")
        out.append("")

    if include_ledger and ans.ledger_rows:
        out.append("## Claims appendix\n")
        out.append("| claim | tag | key | value | units | provenance |")
        out.append("|---|---|---|---|---|---|")
        for r in ans.ledger_rows:
            prov = r.get("source_id") or " ".join(x for x in (r.get("tool"), r.get("tool_version"))
                                                  if x) or "-"
            out.append(f"| {r['claim_id']} | {TAG_ICON.get(r['tag'], r['tag'])} | {r['key']} | "
                       f"{r['value']} | {r.get('units','')} | {prov} |")
        out.append("")
    return "\n".join(out)
