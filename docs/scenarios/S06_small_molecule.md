# S06 — Activity model with baselines

*track: small_molecule · generated from run `run-20261113T013352-c2611e` on 2026-11-12T22:33:52 · pattern `supervisor` · LLM backend `replay/rules (offline)`*

## User request

> Build a QSAR activity model for EGFR from ChEMBL data and tell me honestly whether it beats trivial baselines.

## Expected answer (declared before the run)

Fits a random forest on a Bemis-Murcko scaffold split, reports test RMSE and Spearman, compares against the train-mean and 1-NN Tanimoto baselines, and reports conformal interval coverage.

## What the system planned

- intents: `qsar`
- planner: `callable+cache`
- agents invoked: `target_analyst`, `chemistry_retriever`, `qsar_agent`, `critic`
- tools called (68): `uniprot.search_gene`, `uniprot.entry`, `chembl.target_by_accession`, `uniprot.sequence_features`, `chembl.status`, `chembl.activities`, `rdkit.scaffold`, `qsar.fit`

## Actual result

### What the system did

Planner `callable+cache` routed this request to the intents qsar.

- `S1` **target_analyst** -> resolve_target — every downstream claim needs a verified target identity
- `S2` **chemistry_retriever** -> known_actives — ground design in measured actives, not in LLM memory
- `S3` **qsar_agent** -> fit_and_predict — scaffold-split activity proxy with baselines and conformal intervals
- `S4` **critic** -> cross_check — independent recomputation and applicability-domain audit

Tools actually invoked: `chembl.activities`, `chembl.status`, `chembl.target_by_accession`, `qsar.fit`, `rdkit.scaffold`, `uniprot.entry`, `uniprot.search_gene`, `uniprot.sequence_features`.

### Target

**EGFR** — Epidermal growth factor receptor (Homo sapiens), UniProt `P00533`.
- Sequence length: 1210 residues [E-0003] — RETRIEVED | P00533 @ 2026-11-11
- Experimental structures cross-referenced: 388 [E-0004] — RETRIEVED | P00533 @ 2026-11-11
- ChEMBL target id: `CHEMBL203` [E-0005] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Target identity checks passed: 1 of 1 [E-0027] — uniprot_length_matches_sequence

### Known chemistry (retrieved, not generated)

- ChEMBL release: ChEMBL_37 [E-0008] — RETRIEVED | ChEMBL ChEMBL_37 @ 2026-11-11
- ChEMBL target: CHEMBL203 [E-0009] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Unique actives retrieved: 271 [E-0010] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Median pChEMBL of retrieved actives: 6.72 [E-0011] — COMPUTED | chembl.activities ws-2.x
- Best pChEMBL of retrieved actives: 10.6 [E-0012] — COMPUTED | chembl.activities ws-2.x
- Most potent retrieved compound: CHEMBL29197 [E-0013] — RETRIEVED | CHEMBL29197 @ 2026-11-11

### Activity model

- qsar test rmse: 0.85 [E-0015] — COMPUTED | qsar.fit 1.0
- qsar test spearman: 0.339 [E-0016] — COMPUTED | qsar.fit 1.0
- qsar baseline mean rmse: 1.73 [E-0017] — COMPUTED | qsar.fit 1.0
- qsar baseline 1nn rmse: 0.972 [E-0018] — COMPUTED | qsar.fit 1.0
- qsar n training records: 174 [E-0019] — COMPUTED | qsar.fit 1.0
- qsar conformal empirical coverage: 0.944 [E-0020] — COMPUTED | qsar.fit 1.0
- qsar baseline verdict: model beats both baselines [E-0021] — COMPUTED | qsar.fit 1.0

### Independent cross-check

- critic claims recomputed: 0 [E-0022] — COMPUTED | aletheia.critic 1.0
- critic recomputation mismatches: 0 [E-0023] — COMPUTED | aletheia.critic 1.0
- predicted claims total: 0 [E-0024] — COMPUTED | aletheia.critic 1.0
- predicted claims out of domain: 0 [E-0025] — COMPUTED | aletheia.critic 1.0
- ledger claims total: 25 [E-0026] — COMPUTED | aletheia.critic 1.0
- fewer than two oracles scored the candidates; no consensus check possible

## Verification

- claims ledger: ledger coverage 100.0% (31/31 numeric tokens), 25/28 claims cited, 0 violation(s)
- answer blocked by verifier: **False**
- safety verdict: **ALLOW**

## Invariant checks

- result: **PASS**

## Trace

- run log: `runs/run-20261113T013352-c2611e.jsonl`
- structured answer: `runs/run-20261113T013352-c2611e.answer.json`
- wall time: 0.34 s, LLM calls: 3, tool calls: 68 (68 served from cache)
