# S07 — Analogue generation and ranking

*track: small_molecule · generated from run `run-20261113T013352-84470c` on 2026-11-12T22:33:52 · pattern `supervisor` · LLM backend `replay/rules (offline)`*

## User request

> Generate analogues of erlotinib (C#Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1) for EGFR with better predicted solubility and lower synthetic complexity, then rank them.

## Expected answer (declared before the run)

Runs four independent generators, reports per-generator validity and novelty, applies the cheap-filter gate, screens every structure for hazards, scores with the activity model and ranks by Pareto front with a diverse portfolio.

## What the system planned

- intents: `generate_analogs, property_profile, rank_candidates`
- planner: `callable+cache`
- agents invoked: `target_analyst`, `property_agent`, `chemistry_retriever`, `molecule_generator`, `qsar_agent`, `ranker`, `critic`
- tools called (525): `uniprot.search_gene`, `rdkit.standardize`, `uniprot.entry`, `chembl.target_by_accession`, `uniprot.sequence_features`, `rdkit.descriptors`, `rdkit.druglikeness`, `rdkit.alerts`, `admet.profile`, `chembl.status`, `generators.rule_decorate`, `generators.selfies_mutate`, `chembl.activities`, `generators.validate_proposals`, `rdkit.scaffold`, `rdkit.validate_batch`, `generators.novelty`, `hazard.screen_batch`, `qsar.fit`, `qsar.predict`, `ranking.pareto_front`, `ranking.butina_clusters`, `ranking.portfolio`

## Actual result

### What the system did

Planner `callable+cache` routed this request to the intents generate_analogs, property_profile, rank_candidates.

- `S1` **target_analyst** -> resolve_target — every downstream claim needs a verified target identity
- `S2` **chemistry_retriever** -> known_actives — ground design in measured actives, not in LLM memory
- `S3` **property_agent** -> profile_molecules — descriptors and alerts for the molecules named by the user
- `S4` **molecule_generator** -> generate — three independent generators limit single-model bias
- `S5` **property_agent** -> profile_candidates — cheap filters before any expensive oracle (funnel gate 1)
- `S6` **qsar_agent** -> fit_and_predict — scaffold-split activity proxy with baselines and conformal intervals
- `S7` **ranker** -> rank_and_select — multi-objective Pareto ranking + diversity-aware portfolio
- `S8` **critic** -> cross_check — independent recomputation and applicability-domain audit

Tools actually invoked: `admet.profile`, `chembl.activities`, `chembl.status`, `chembl.target_by_accession`, `generators.novelty`, `generators.rule_decorate`, `generators.selfies_mutate`, `generators.validate_proposals`, `hazard.screen_batch`, `qsar.fit`, `qsar.predict`, `ranking.butina_clusters`, `ranking.pareto_front`, `ranking.portfolio`, `rdkit.alerts`, `rdkit.descriptors`, `rdkit.druglikeness`, `rdkit.scaffold`, `rdkit.standardize`, `rdkit.validate_batch`, `uniprot.entry`, `uniprot.search_gene`, `uniprot.sequence_features`.

### Target

**EGFR** — Epidermal growth factor receptor (Homo sapiens), UniProt `P00533`.
- Sequence length: 1210 residues [E-0004] — RETRIEVED | P00533 @ 2026-11-11
- Experimental structures cross-referenced: 388 [E-0005] — RETRIEVED | P00533 @ 2026-11-11
- ChEMBL target id: `CHEMBL203` [E-0006] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Target identity checks passed: 1 of 1 [E-1874] — uniprot_length_matches_sequence

### Known chemistry (retrieved, not generated)

- ChEMBL release: ChEMBL_37 [E-0029] — RETRIEVED | ChEMBL ChEMBL_37 @ 2026-11-11
- ChEMBL target: CHEMBL203 [E-0030] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Unique actives retrieved: 271 [E-0031] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Median pChEMBL of retrieved actives: 6.72 [E-0032] — COMPUTED | chembl.activities ws-2.x
- Best pChEMBL of retrieved actives: 10.6 [E-0033] — COMPUTED | chembl.activities ws-2.x
- Most potent retrieved compound: CHEMBL29197 [E-0034] — RETRIEVED | CHEMBL29197 @ 2026-11-11

### Generation

- llm edit validity: 1 [E-0035] — COMPUTED | generators.validate_proposals 1.0
- G1 rule decorate n generated: 36 [E-0036] — COMPUTED | rdkit.validate_batch 2026.09.2
- G1 rule decorate frac novel: 0 [E-0037] — COMPUTED | generators.novelty 1.0
- G1 rule decorate mean max similarity: 0.682 [E-0038] — COMPUTED | generators.novelty 1.0
- G3 selfies mutate n generated: 40 [E-0039] — COMPUTED | rdkit.validate_batch 2026.09.2
- G3 selfies mutate frac novel: 0.65 [E-0040] — COMPUTED | generators.novelty 1.0
- G3 selfies mutate mean max similarity: 0.317 [E-0041] — COMPUTED | generators.novelty 1.0
- G4 llm edits n generated: 10 [E-0042] — COMPUTED | rdkit.validate_batch 2026.09.2
- G4 llm edits frac novel: 0.1 [E-0043] — COMPUTED | generators.novelty 1.0
- G4 llm edits mean max similarity: 0.787 [E-0044] — COMPUTED | generators.novelty 1.0
- hazard screened structures: 86 [E-0045] — COMPUTED | hazard.screen_batch 1.0
- candidates after dedup and safety: 86 [E-0046] — COMPUTED | aletheia.generator 1.0

### Activity model

- qsar test rmse: 0.85 [E-1856] — COMPUTED | qsar.fit 1.0
- qsar test spearman: 0.339 [E-1857] — COMPUTED | qsar.fit 1.0
- qsar baseline mean rmse: 1.73 [E-1858] — COMPUTED | qsar.fit 1.0
- qsar baseline 1nn rmse: 0.972 [E-1859] — COMPUTED | qsar.fit 1.0
- qsar n training records: 174 [E-1860] — COMPUTED | qsar.fit 1.0
- qsar conformal empirical coverage: 0.944 [E-1861] — COMPUTED | qsar.fit 1.0
- qsar baseline verdict: model beats both baselines [E-1862] — COMPUTED | qsar.fit 1.0

### Ranking and portfolio

- pareto front size: 2 [E-1863] — COMPUTED | ranking.pareto_front 1.0
- n chemotype clusters: 3 [E-1864] — COMPUTED | ranking.butina_clusters 1.0
- portfolio size: 5 [E-1865] — COMPUTED | ranking.portfolio 1.0
- probability that the portfolio contains at least one hit: **withheld** [E-1866, E-1867, E-1868] — the hit-probability calibrator fails its pre-registered calibration criterion on the held-out scaffold-split test fold, so the value is kept as a ledger diagnostic rather than published (docs/preregistration.md, figures/calibration.png)

### Property profile — user:C#Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1

`C#Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1`

- MW: 393.443 Da [E-0009] — COMPUTED | rdkit.descriptors 2026.09.2
- cLogP: 3.405  [E-0010] — COMPUTED | rdkit.descriptors 2026.09.2
- TPSA: 74.73 A^2 [E-0011] — COMPUTED | rdkit.descriptors 2026.09.2
- rotatable bonds: 10  [E-0014] — COMPUTED | rdkit.descriptors 2026.09.2
- H-bond donors: 1  [E-0012] — COMPUTED | rdkit.descriptors 2026.09.2
- H-bond acceptors: 7  [E-0013] — COMPUTED | rdkit.descriptors 2026.09.2
- heavy atoms: 29  [E-0017] — COMPUTED | rdkit.descriptors 2026.09.2
- QED: 0.418  [E-0022] — COMPUTED | rdkit.descriptors 2026.09.2
- SA score: 2.478  [E-0023] — COMPUTED | rdkit.descriptors 2026.09.2
- Ro5 violations: 0  [E-0024] — COMPUTED | rdkit.druglikeness 2026.09.2
- structural alerts: 2  [E-0025] — COMPUTED | rdkit.alerts 2026.09.2
- ESOL logS: -4.173 log10(mol/L) [E-0026] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- CNS-MPO-like: 5.188  [E-0027] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- structural alerts: BRENK:Aliphatic_long_chain; BRENK:triple_bond

### Independent cross-check

- critic claims recomputed: 8 [E-1869] — COMPUTED | aletheia.critic 1.0
- critic recomputation mismatches: 0 [E-1870] — COMPUTED | aletheia.critic 1.0
- predicted claims total: 177 [E-1871] — COMPUTED | aletheia.critic 1.0
- predicted claims out of domain: 0 [E-1872] — COMPUTED | aletheia.critic 1.0
- ledger claims total: 1872 [E-1873] — COMPUTED | aletheia.critic 1.0
- 177 predicted value(s) have no applicability-domain verdict and are reported as such
- fewer than two oracles scored the candidates; no consensus check possible

### Degradations reported

- BRICS generator skipped: no retrieved actives to fragment

## Verification

- claims ledger: ledger coverage 100.0% (74/74 numeric tokens), 56/1875 claims cited, 0 violation(s)
- answer blocked by verifier: **False**
- safety verdict: **ALLOW**

## Invariant checks

- result: **PASS**

## Trace

- run log: `runs/run-20261113T013352-84470c.jsonl`
- structured answer: `runs/run-20261113T013352-84470c.answer.json`
- wall time: 8.4 s, LLM calls: 4, tool calls: 525 (516 served from cache)
