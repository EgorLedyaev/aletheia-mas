# S01 — Target brief from a plain-language question

*track: protein · generated from run `run-20261113T013349-767fdb` on 2026-11-12T22:33:50 · pattern `supervisor` · LLM backend `replay/rules (offline)`*

## User request

> Give me a brief on the EGFR kinase target: what is known, which structures exist, and what are the most potent known inhibitors in ChEMBL?

## Expected answer (declared before the run)

Resolves EGFR to UniProt P00533, reports sequence length and the number of cross-referenced PDB entries, selects a structure, retrieves ChEMBL actives and reports the median and best pChEMBL with the ChEMBL ids.

## What the system planned

- intents: `target_brief, protein_analysis, ligand_lookup`
- planner: `callable+cache`
- agents invoked: `target_analyst`, `chemistry_retriever`, `structure_analyst`, `critic`
- tools called (72): `uniprot.search_gene`, `uniprot.entry`, `chembl.target_by_accession`, `uniprot.sequence_features`, `pdb.download`, `pdb.ligands`, `pdb.entry`, `pdb.chain_sequences`, `chembl.status`, `pocket.detect`, `chembl.activities`, `rdkit.scaffold`

## Actual result

### What the system did

Planner `callable+cache` routed this request to the intents target_brief, protein_analysis, ligand_lookup.

- `S1` **target_analyst** -> resolve_target — every downstream claim needs a verified target identity
- `S2` **chemistry_retriever** -> known_actives — ground design in measured actives, not in LLM memory
- `S3` **structure_analyst** -> analyse_structure — binding-site detection on the selected structure
- `S4` **critic** -> cross_check — independent recomputation and applicability-domain audit

Tools actually invoked: `chembl.activities`, `chembl.status`, `chembl.target_by_accession`, `pdb.chain_sequences`, `pdb.download`, `pdb.entry`, `pdb.ligands`, `pocket.detect`, `rdkit.scaffold`, `uniprot.entry`, `uniprot.search_gene`, `uniprot.sequence_features`.

### Target

**EGFR** — Epidermal growth factor receptor (Homo sapiens), UniProt `P00533`.
- Sequence length: 1210 residues [E-0003] — RETRIEVED | P00533 @ 2026-11-11
- Experimental structures cross-referenced: 388 [E-0004] — RETRIEVED | P00533 @ 2026-11-11
- Structure selected: `8A27` at 1.07 A resolution [E-0008]
- Co-crystal ligand component id: `KY9` [E-0010] — COMPUTED | pdb.ligands rcsb-rest-v1
- ChEMBL target id: `CHEMBL203` [E-0005] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Target identity checks passed: 2 of 2 [E-0026] — uniprot_length_matches_sequence; structure_sequence_matches_uniprot

### Known chemistry (retrieved, not generated)

- ChEMBL release: ChEMBL_37 [E-0011] — RETRIEVED | ChEMBL ChEMBL_37 @ 2026-11-11
- ChEMBL target: CHEMBL203 [E-0015] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Unique actives retrieved: 271 [E-0016] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Median pChEMBL of retrieved actives: 6.72 [E-0017] — COMPUTED | chembl.activities ws-2.x
- Best pChEMBL of retrieved actives: 10.6 [E-0018] — COMPUTED | chembl.activities ws-2.x
- Most potent retrieved compound: CHEMBL29197 [E-0019] — RETRIEVED | CHEMBL29197 @ 2026-11-11

### Binding site

- top pocket volume: 445 A^3 [E-0012] — COMPUTED | pocket.detect ligsite-like-1.0
- n pockets detected: 3  [E-0013] — COMPUTED | pocket.detect ligsite-like-1.0
- pocket to cocrystal distance: 0.44 A [E-0014] — COMPUTED | pocket.detect ligsite-like-1.0
- localisation check: the detected cavity nearest the crystallographic ligand centroid is pocket rank 1, within 5 A of it

### Independent cross-check

- critic claims recomputed: 0 [E-0021] — COMPUTED | aletheia.critic 1.0
- critic recomputation mismatches: 0 [E-0022] — COMPUTED | aletheia.critic 1.0
- predicted claims total: 0 [E-0023] — COMPUTED | aletheia.critic 1.0
- predicted claims out of domain: 0 [E-0024] — COMPUTED | aletheia.critic 1.0
- ledger claims total: 24 [E-0025] — COMPUTED | aletheia.critic 1.0
- fewer than two oracles scored the candidates; no consensus check possible

## Verification

- claims ledger: ledger coverage 100.0% (27/27 numeric tokens), 23/27 claims cited, 0 violation(s)
- answer blocked by verifier: **False**
- safety verdict: **ALLOW**

## Invariant checks

- result: **PASS**

## Trace

- run log: `runs/run-20261113T013349-767fdb.jsonl`
- structured answer: `runs/run-20261113T013349-767fdb.answer.json`
- wall time: 1.25 s, LLM calls: 3, tool calls: 72 (72 served from cache)
