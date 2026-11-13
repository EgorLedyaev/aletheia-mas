"""Reporter agent: renders the answer and submits it to the claims verifier.

Two honesty mechanisms live here:
  1. every sentence containing a number is generated *from* an Evidence record, so the printed
     digits are the tool's digits;
  2. the optional LLM narrative is verified on its own before inclusion -- if the model slips a
     number into it, the narrative is dropped and the drop is reported, instead of the whole
     answer failing or the number being published.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from ..core.contracts import AgentResult, AnswerBlock, Candidate, FinalAnswer
from ..core.context import RunContext
from ..core.ledger import AnswerVerifier
from .base import Agent

NARRATIVE_SYSTEM = (
    "You write the interpretation paragraph of a drug-discovery report. "
    "ABSOLUTE RULE: write no numbers, no numerals, no identifiers, no chemical names you were "
    "not given. Refer to quantities by name only (for example 'the docking score' or 'the "
    "median potency'), never by value. Two to four sentences. State what the result supports and "
    "what it does not. Do not claim efficacy, safety or clinical relevance."
)


def _fmt(ev: Any, precision: int = 3) -> str:
    return ev.render_value(precision)


class ReporterAgent(Agent):
    name = "reporter"
    description = "Builds the user-facing answer with provenance badges and verifies it."
    tools: List[str] = []

    def _key_claims(self, ctx: RunContext, keys: List[str]) -> List[Any]:
        out = []
        for k in keys:
            for ev in ctx.ledger.claims.values():
                if ev.key == k:
                    out.append(ev)
        return out

    def build(self, ctx: RunContext, plan: Any, results: List[AgentResult]) -> FinalAnswer:
        blocks: List[AnswerBlock] = []
        L = ctx.ledger

        # -- what the system did ------------------------------------------
        agents_used = [r.agent for r in results]
        tool_names = sorted({c.tool for c in ctx.tools.history})
        steps_txt = "\n".join(
            f"- `{s.step_id}` **{s.agent}** -> {s.action}" + (f" — {s.rationale}" if s.rationale else "")
            for s in plan.steps)
        blocks.append(AnswerBlock(
            title="What the system did",
            text=(f"Planner `{plan.planner}` routed this request to the intents "
                  f"{', '.join(i.value for i in plan.intents)}.\n\n{steps_txt}\n\n"
                  f"Tools actually invoked: {', '.join('`'+t+'`' for t in tool_names)}."),
            # Step ids and tool names are structural labels, not claims. Their digits are
            # exempted explicitly (e.g. "B-4" tokenises to "4" while "S1" does not, which once
            # made the two orchestration patterns look different when they were not).
            exempt_numbers=[tok for s in plan.steps for tok in re.findall(r"\d+", s.step_id)] +
                           [s.step_id for s in plan.steps] +
                           [t.split(".")[-1] for t in tool_names] +
                           [tok for t in tool_names for tok in re.findall(r"\d+", t)],
            claim_ids=[]))

        # -- target --------------------------------------------------------
        card = ctx.blackboard.get("target_card")
        if card:
            cl = card.get("claims", {})
            cited = [c for c in cl.values() if c]
            lines = [f"**{card.get('gene') or card.get('accession')}** — {card.get('name')} "
                     f"({card.get('organism')}), UniProt `{card.get('accession')}`."]
            ln = L.get(cl.get("length")) if cl.get("length") else None
            if ln:
                lines.append(f"- Sequence length: {_fmt(ln)} residues [{ln.claim_id}] — {ln.badge()}")
            npdb = L.get(cl.get("n_pdb")) if cl.get("n_pdb") else None
            if npdb:
                lines.append(f"- Experimental structures cross-referenced: {_fmt(npdb)} "
                             f"[{npdb.claim_id}] — {npdb.badge()}")
            if card.get("chosen_pdb"):
                rs = L.get(cl.get("resolution")) if cl.get("resolution") else None
                res_txt = f" at {_fmt(rs)} A resolution [{rs.claim_id}]" if rs and rs.value else ""
                lines.append(f"- Structure selected: `{card['chosen_pdb']}`{res_txt}")
                if rs:
                    cited.append(rs.claim_id)
            lig = next((e for e in L.claims.values() if e.key == "cocrystal_ligand"), None)
            if lig and card.get("chosen_pdb"):
                lines.append(f"- Co-crystal ligand component id: `{lig.value}` "
                             f"[{lig.claim_id}] — {lig.badge()}")
                cited.append(lig.claim_id)
            ct = next((e for e in L.claims.values() if e.key == "chembl_target_id"), None)
            if ct:
                lines.append(f"- ChEMBL target id: `{ct.value}` [{ct.claim_id}] — {ct.badge()}")
                cited.append(ct.claim_id)
            if card.get("alphafold"):
                af = card["alphafold"]
                pl = next((e for e in L.claims.values() if e.key == "alphafold_mean_plddt"), None)
                if pl:
                    lines.append(f"- No usable experimental structure; AlphaFold DB model "
                                 f"`{af.get('entry_id')}` used, mean pLDDT {_fmt(pl)} "
                                 f"[{pl.claim_id}] — {pl.badge()}")
                    cited.append(pl.claim_id)
            checks = card.get("identity_checks", [])
            ok_n = sum(1 for c in checks if c["pass"])
            idc = L.register(tag="COMPUTED", key="identity_checks_passed", value=ok_n,
                             tool="aletheia.identity_check", tool_version="1.0",
                             params_hash=card.get("accession", "-"), subject=card.get("accession"),
                             note="; ".join(f"{c['check']}={c['pass']}" for c in checks))
            total = L.register(tag="COMPUTED", key="identity_checks_total", value=len(checks),
                               tool="aletheia.identity_check", tool_version="1.0",
                               params_hash=card.get("accession", "-"))
            lines.append(f"- Target identity checks passed: {_fmt(idc)} of {_fmt(total)} "
                         f"[{idc.claim_id}] — {'; '.join(c['check'] for c in checks)}")
            cited += [idc.claim_id, total.claim_id]
            blocks.append(AnswerBlock(title="Target", text="\n".join(lines),
                                      claim_ids=[c for c in cited if c],
                                      structures=[card.get("accession")] +
                                                 ([card["chosen_pdb"]] if card.get("chosen_pdb") else [])))

        # -- retrieved chemistry -------------------------------------------
        ret = next((r for r in results if r.agent == "chemistry_retriever" and r.ok), None)
        if ret:
            ids = [e.claim_id for e in ret.evidence]
            lines = []
            for key, label in [("chembl_release", "ChEMBL release"),
                               ("chembl_target_id", "ChEMBL target"),
                               ("n_unique_actives", "Unique actives retrieved"),
                               ("pchembl_median", "Median pChEMBL of retrieved actives"),
                               ("pchembl_max", "Best pChEMBL of retrieved actives"),
                               ("most_potent_active", "Most potent retrieved compound")]:
                ev = next((e for e in ret.evidence if e.key == key), None)
                if ev:
                    lines.append(f"- {label}: {_fmt(ev)} [{ev.claim_id}] — {ev.badge()}")
            if lines:
                blocks.append(AnswerBlock(title="Known chemistry (retrieved, not generated)",
                                          text="\n".join(lines), claim_ids=ids))

        # -- generation ------------------------------------------------------
        gen = next((r for r in results if r.agent == "molecule_generator" and r.ok), None)
        if gen:
            lines = []
            for ev in gen.evidence:
                lines.append(f"- {ev.key.replace('_', ' ')}: {_fmt(ev)} [{ev.claim_id}] — {ev.badge()}")
            blocks.append(AnswerBlock(title="Generation", text="\n".join(lines),
                                      claim_ids=[e.claim_id for e in gen.evidence]))

        # -- binding site ------------------------------------------------------
        sa = next((x for x in results if x.agent == "structure_analyst" and x.evidence), None)
        if sa:
            lines = []
            for ev2 in sa.evidence:
                lines.append(f"- {ev2.key.replace('_', ' ')}: {_fmt(ev2)} {ev2.units or ''} "
                             f"[{ev2.claim_id}] — {ev2.badge()}")
            val = (sa.data or {}).get("validation")
            if val:
                lines.append(f"- localisation check: the detected cavity nearest the "
                             f"crystallographic ligand centroid is pocket rank "
                             f"{val['best_pocket_rank']}, "
                             f"{'within' if val['hit_within_5A'] else 'beyond'} 5 A of it")
            blocks.append(AnswerBlock(title="Binding site", text="\n".join(lines),
                                      claim_ids=[e.claim_id for e in sa.evidence],
                                      exempt_numbers=[str(val["best_pocket_rank"]), "5"] if val else []))

        # -- docking ----------------------------------------------------------
        dock = next((r for r in results if r.agent == "docking_agent"), None)
        if dock and dock.evidence:
            lines = []
            for ev in dock.evidence:
                suffix = ""
                if ev.validation:
                    suffix = " — validation: " + ", ".join(f"{k}={v}" for k, v in ev.validation.items())
                lines.append(f"- {ev.key.replace('_', ' ')}: {_fmt(ev)} {ev.units or ''} "
                             f"[{ev.claim_id}] — {ev.badge()}{suffix}")
            blocks.append(AnswerBlock(title="Docking", text="\n".join(lines),
                                      claim_ids=[e.claim_id for e in dock.evidence]))

        # -- qsar --------------------------------------------------------------
        qs = next((r for r in results if r.agent == "qsar_agent"), None)
        if qs and qs.evidence:
            lines = [f"- {ev.key.replace('_', ' ')}: {_fmt(ev)} [{ev.claim_id}] — {ev.badge()}"
                     for ev in qs.evidence]
            blocks.append(AnswerBlock(title="Activity model", text="\n".join(lines),
                                      claim_ids=[e.claim_id for e in qs.evidence]))

        # -- ranking -------------------------------------------------------------
        rk = next((r for r in results if r.agent == "ranker"), None)
        if rk and rk.evidence:
            # A probability whose calibrator failed its pre-registered criterion stays in the
            # ledger as a diagnostic but is not published: an uncalibrated number in an answer is
            # exactly what this system exists to prevent.
            withheld = set((rk.data or {}).get("withheld_keys") or [])
            lines = [f"- {ev.key.replace('_', ' ')}: {_fmt(ev)} [{ev.claim_id}] — {ev.badge()}"
                     for ev in rk.evidence if ev.key not in withheld]
            hidden = [ev for ev in rk.evidence if ev.key in withheld]
            if hidden:
                lines.append(
                    "- probability that the portfolio contains at least one hit: **withheld** "
                    "[" + ", ".join(ev.claim_id for ev in hidden) + "] — the hit-probability "
                    "calibrator fails its pre-registered calibration criterion on the held-out "
                    "scaffold-split test fold, so the value is kept as a ledger diagnostic "
                    "rather than published (docs/preregistration.md, figures/calibration.png)")
            blocks.append(AnswerBlock(title="Ranking and portfolio", text="\n".join(lines),
                                      claim_ids=[e.claim_id for e in rk.evidence]))

        # -- properties of user molecules -----------------------------------------
        prop = next((r for r in results if r.agent == "property_agent" and
                     r.data.get("candidates")), None)
        if prop:
            for c in prop.data["candidates"][:5]:
                cl = c["property_claims"]
                keys = [("MolWt", "MW", "Da"), ("cLogP", "cLogP", ""), ("TPSA", "TPSA", "A^2"),
                        ("RotB", "rotatable bonds", ""), ("HBD", "H-bond donors", ""),
                        ("HBA", "H-bond acceptors", ""), ("HeavyAtoms", "heavy atoms", ""),
                        ("QED", "QED", ""), ("SAscore", "SA score", ""),
                        ("lipinski_violations", "Ro5 violations", ""),
                        ("n_structural_alerts", "structural alerts", ""),
                        ("esol_logS", "ESOL logS", "log10(mol/L)"),
                        ("cns_mpo_like", "CNS-MPO-like", "")]
                lines = []
                cited = []
                for k, label, unit in keys:
                    cid = cl.get(k)
                    ev = L.get(cid) if cid else None
                    if ev is None:
                        continue
                    lines.append(f"- {label}: {_fmt(ev)} {unit} [{ev.claim_id}] — {ev.badge()}")
                    cited.append(ev.claim_id)
                if c.get("flags"):
                    lines.append("- structural alerts: " + "; ".join(c["flags"][:6]))
                blocks.append(AnswerBlock(
                    title=f"Property profile — {c['origin']}",
                    text=f"`{c['smiles']}`\n\n" + "\n".join(lines),
                    claim_ids=cited, structures=[c["smiles"]]))

        # -- critic ---------------------------------------------------------------
        crit = next((r for r in results if r.agent == "critic"), None)
        if crit and crit.evidence:
            lines = [f"- {ev.key.replace('_', ' ')}: {_fmt(ev)} [{ev.claim_id}] — {ev.badge()}"
                     for ev in crit.evidence]
            if crit.messages:
                lines += [f"- {m}" for m in crit.messages]
            blocks.append(AnswerBlock(title="Independent cross-check", text="\n".join(lines),
                                      claim_ids=[e.claim_id for e in crit.evidence],
                                      level="note"))

        # -- LLM narrative (number-free, verified separately) -----------------------
        narrative = self._narrative(ctx, plan, blocks)
        if narrative:
            blocks.append(narrative)

        ans = FinalAnswer(
            run_id=ctx.run_id, query=ctx.query, plan=plan, blocks=blocks,
            candidates=[Candidate(**c) for c in ctx.blackboard.get("candidates", [])][:50],
            target=None, safety=ctx.safety, degraded=list(ctx.degraded),
            ledger_rows=L.to_rows(), source=ctx.source_mix(),
            tool_calls=[c.model_dump() for c in ctx.tools.history],
            agent_results=[{"agent": r.agent, "step_id": r.step_id, "ok": r.ok,
                            "degraded": r.degraded, "duration_s": r.duration_s,
                            "error": r.error, "messages": r.messages} for r in results],
            duration_s=round(ctx.elapsed, 2),
            cost={"llm_calls": len(ctx.llm.calls),
                  "llm_backend": ctx.llm.backend_name,
                  "tool_calls": len(ctx.tools.history),
                  "cached_tool_calls": sum(1 for c in ctx.tools.history if c.cached)})
        return ans

    def _narrative(self, ctx: RunContext, plan: Any, blocks: List[AnswerBlock]) -> Optional[AnswerBlock]:
        facts = []
        for ev in list(ctx.ledger.claims.values())[:40]:
            facts.append(f"{ev.key} = {ev.render_value()} ({ev.tag.value})")
        prompt = ("Findings available (do not quote any values):\n" + "\n".join("- " + f for f in facts) +
                  f"\n\nUser request: {ctx.query}\n\nWrite the interpretation paragraph.")
        resp = ctx.llm.complete(prompt, system=NARRATIVE_SYSTEM, purpose="narrative",
                                max_tokens=400)
        if resp.error or not resp.text.strip():
            return None
        block = AnswerBlock(title="Interpretation (LLM reasoning)",
                            text=resp.text.strip(), claim_ids=[], level="note")
        # The narrative is required to be number-free: a value in LLM prose has no provenance even
        # if an identical value happens to exist in the ledger, so any numeric token kills it.
        from ..core.ledger import DATE_RE, ID_RE, NUM_RE
        stray = [m.group() for m in NUM_RE.finditer(ID_RE.sub(" ", DATE_RE.sub(" ", block.text)))]
        probe = AnswerVerifier(ctx.ledger, strict_citation=False, allow_global_pool=True)
        rep = probe.verify([block])
        if stray:
            ctx.degrade(f"LLM narrative contained numeric tokens {stray[:5]} and was dropped; "
                        "numbers in prose have no provenance")
            ctx.tracer.emit("narrative_rejected", reason="numeric_token", tokens=stray[:5])
            return None
        if not rep.ok:
            ctx.degrade("LLM narrative rejected by the claims verifier "
                        f"({len(rep.violations)} violation(s)); it was dropped, not published")
            ctx.tracer.emit("narrative_rejected", violations=[v.kind for v in rep.violations])
            return None
        block.text += ("\n\n*This paragraph is LLM reasoning over the findings above. It is tagged "
                       "HYPOTHESIS: it contains no numbers of its own and was itself checked "
                       "against the claims ledger before publication.*")
        return block

    def act(self, ctx: RunContext, step) -> AgentResult:
        t0 = time.time()
        return AgentResult(agent=self.name, step_id=getattr(step, "step_id", "S0"),
                           duration_s=round(time.time() - t0, 3))
