# SOTA audit — LLM agents for chemistry & drug discovery
Audit date: 2026-11-11. Retrieval: OpenAlex API (`works?search=`), authenticated.
Every row below corresponds to a record actually returned by that API in this session; nothing
is cited from memory. Citation counts are OpenAlex `cited_by_count` on the audit date.

## A. Systems and studies retrieved (verified records)

| Year | System / work | Venue | Cited | DOI |
|---|---|---|---|---|
| 2024 | Augmenting LLMs with chemistry tools (ChemCrow) | Nature Machine Intelligence | 1704 | 10.1038/s42256-024-00832-8 |
| 2023 | Autonomous chemical research with LLMs (Coscientist) | Nature | 1785 | 10.1038/s41586-023-06792-0 |
| 2025 | A Multiagent-Driven Robotic AI Chemist | JACS | 210 | 10.1021/jacs.4c17738 |
| 2024 | DrugAgent: automating AI-aided drug-discovery programming | arXiv | 89 | 10.48550/arxiv.2411.15692 |
| 2026 | RAG-Enhanced Collaborative LLM Agents for Drug Discovery | AAAI | 36 | 10.1609/aaai.v40i1.37020 |
| 2025 | DrugPilot: parameterized reasoning agent for drug discovery | Research Square | 29 | 10.21203/rs.3.rs-7489358/v |
| 2025 | LLM Agent Swarm for Hypothesis-Driven Drug Discovery | arXiv | 21 | 10.48550/arxiv.2504.17967 |
| 2026 | Mozi: Governed Autonomy for Drug Discovery LLM Agents | arXiv | 14 | 10.48550/arxiv.2603.03655 |
| 2026 | LLM Agent for Modular Task Execution in Drug Discovery | J. Chem. Inf. Model. | 14 | 10.1021/acs.jcim.5c02454 |
| 2026 | A Demonstration of an LLM-based MAS for Drug Discovery | AAMAS | 1 | 10.65109/kapy7208 |
| 2026 | Swarms of LLM agents for protein sequence design (exp. validated) | Digital Discovery | 14 | 10.1039/d6dd00282j |
| 2026 | Protein Design with Agent Rosetta | arXiv | 2 | 10.48550/arxiv.2603.15952 |
| 2025 | DynaMate: autonomous agent for protein-ligand MD | arXiv | 14 | 10.48550/arxiv.2512.10034 |
| 2025 | El Agente: autonomous agent for quantum chemistry | Matter | 112 | 10.1016/j.matt.2025.102263 |
| 2025 | TxGemma: efficient and agentic LLMs for therapeutics | arXiv | 77 | 10.48550/arxiv.2504.06196 |
| 2024 | ChemSafetyBench: benchmarking LLM safety in chemistry | arXiv | 33 | 10.48550/arxiv.2411.16736 |
| 2026 | AgentHallu: benchmarking hallucination attribution of LLM agents | EMNLP | 27 | 10.18653/2026.emnlp-main.9 |
| 2026 | Benchmarking/behavioral characterization of LLM agents for protein design | bioRxiv | 6 | 10.64898/2026.05.06.723381 |
| 2026 | Evaluating autonomous LLM agents across molecular prediction/optimization | bioRxiv | 0 | 10.64898/2026.10.01.755314 |
| 2024 | A review of LLMs and autonomous agents in chemistry | Chemical Science | 382 | 10.1039/d4sc03921a |

We did not read the full text of every record inside the 2 h audit box; the table is a verified
*existence and positioning* map, not a claim about each system's internals. Statements below that
go beyond titles/abstracts are marked [INFERRED].

## B. What the field already does well (and we therefore do not re-invent)
1. **Tool-calling chemistry agents** are established (ChemCrow, Coscientist). Giving an LLM RDKit +
   databases is no longer novel on its own.
2. **Role specialisation** (planner / retriever / predictor / critic) recurs across DrugAgent,
   DrugPilot, agent swarms. Multi-agent decomposition is the default, not a differentiator.
3. **RAG grounding** of agent answers in literature/database records is active work (AAAI 2026 entry).

## C. The gap this project targets
The benchmark literature retrieved above (AgentHallu 2026; the two 2026 agent-benchmark preprints;
ChemSafetyBench 2024) exists *because* agent outputs are still not mechanically traceable: an agent
can emit a docking score or an IC50 that no tool ever produced, and nothing in the loop stops it.
Mozi (2026) frames the same problem as "governed autonomy". [INFERRED from titles/venues.]

**Design decision D1 — the ledger is the product.** Aletheia's differentiator is not the agent roster
but a *claims ledger with a blocking verifier*: every number and structure in a final answer must
resolve to a registered tool-output id, or the answer is refused. See `aletheia/core/ledger.py`.

**Design decision D2 — four provenance tags, rendered.** COMPUTED / PREDICTED / RETRIEVED /
HYPOTHESIS are carried per value and printed in the user-facing answer, so a jury can see which
parts are arithmetic, which are a model guess with an uncertainty, which came from a database
record with an accession, and which is LLM reasoning.

**Design decision D3 — validation attached to every oracle.** Docking scores ship with a redocking
RMSD and a decoy-enrichment number for the same receptor; QSAR ships with scaffold-split metrics,
baselines, conformal intervals and an applicability-domain flag. An oracle without a validation
number is reported as unvalidated rather than quoted bare.

**Design decision D4 — safety as an agent, not a prompt.** ChemSafetyBench's existence says prompt
instructions are insufficient; the guardrail is a separate gate with a decision table and an audit
log, running before planning and again on every generated structure.

**Design decision D5 — orchestration chosen by measurement.** Two patterns (hierarchical supervisor
vs. blackboard fan-out) are implemented behind identical contracts and benchmarked on our scenario
suite; the loser stays in the repo as an ablation, which is also how we answer "why this design".
