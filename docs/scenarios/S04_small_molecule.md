# S04 — Known actives and scaffolds for a second target

*track: small_molecule · generated from run `run-20261113T013351-3031f3` on 2026-11-12T22:33:51 · pattern `supervisor` · LLM backend `replay/rules (offline)`*

## User request

> Which compounds are the most potent known CDK2 inhibitors in ChEMBL, and how many distinct scaffolds do the top actives use?

## Expected answer (declared before the run)

Resolves CDK2 to its UniProt accession and ChEMBL target, retrieves actives, and reports the Bemis-Murcko scaffold count over the most potent subset.

## What the system planned

- intents: `ligand_lookup, protein_analysis`
- planner: `callable+cache`
- agents invoked: `target_analyst`, `chemistry_retriever`, `structure_analyst`, `critic`
- tools called (72): `uniprot.search_gene`, `uniprot.entry`, `chembl.target_by_accession`, `uniprot.sequence_features`, `pdb.download`, `pdb.ligands`, `pdb.entry`, `pdb.chain_sequences`, `chembl.status`, `pocket.detect`, `chembl.activities`, `rdkit.scaffold`

## Actual result

### What the system did

Planner `callable+cache` routed this request to the intents ligand_lookup, protein_analysis.

- `S1` **target_analyst** -> resolve_target — every downstream claim needs a verified target identity
- `S2` **chemistry_retriever** -> known_actives — ground design in measured actives, not in LLM memory
- `S3` **structure_analyst** -> analyse_structure — binding-site detection on the selected structure
- `S4` **critic** -> cross_check — independent recomputation and applicability-domain audit

Tools actually invoked: `chembl.activities`, `chembl.status`, `chembl.target_by_accession`, `pdb.chain_sequences`, `pdb.download`, `pdb.entry`, `pdb.ligands`, `pocket.detect`, `rdkit.scaffold`, `uniprot.entry`, `uniprot.search_gene`, `uniprot.sequence_features`.

### Target

**CDK2** — Cyclin-dependent kinase 2 (Homo sapiens), UniProt `P24941`.
- Sequence length: 298 residues [E-0003] — RETRIEVED | P24941 @ 2026-11-11
- Experimental structures cross-referenced: 522 [E-0004] — RETRIEVED | P24941 @ 2026-11-11
- Structure selected: `6Q4G` at 0.98 A resolution [E-0008]
- Co-crystal ligand component id: `HJK` [E-0010] — COMPUTED | pdb.ligands rcsb-rest-v1
- ChEMBL target id: `CHEMBL301` [E-0005] — RETRIEVED | CHEMBL301 @ 2026-11-11
- Target identity checks passed: 2 of 2 [E-0026] — uniprot_length_matches_sequence; structure_sequence_matches_uniprot

### Known chemistry (retrieved, not generated)

- ChEMBL release: ChEMBL_37 [E-0011] — RETRIEVED | ChEMBL ChEMBL_37 @ 2026-11-11
- ChEMBL target: CHEMBL301 [E-0015] — RETRIEVED | CHEMBL301 @ 2026-11-11
- Unique actives retrieved: 267 [E-0016] — RETRIEVED | CHEMBL301 @ 2026-11-11
- Median pChEMBL of retrieved actives: 7.11 [E-0017] — COMPUTED | chembl.activities ws-2.x
- Best pChEMBL of retrieved actives: 9.48 [E-0018] — COMPUTED | chembl.activities ws-2.x
- Most potent retrieved compound: CHEMBL317703 [E-0019] — RETRIEVED | CHEMBL317703 @ 2026-11-11

### Binding site

- top pocket volume: 222 A^3 [E-0012] — COMPUTED | pocket.detect ligsite-like-1.0
- n pockets detected: 4  [E-0013] — COMPUTED | pocket.detect ligsite-like-1.0
- pocket to cocrystal distance: 0.69 A [E-0014] — COMPUTED | pocket.detect ligsite-like-1.0
- localisation check: the detected cavity nearest the crystallographic ligand centroid is pocket rank 1, within 5 A of it

### Independent cross-check

- critic claims recomputed: 0 [E-0021] — COMPUTED | aletheia.critic 1.0
- critic recomputation mismatches: 0 [E-0022] — COMPUTED | aletheia.critic 1.0
- predicted claims total: 0 [E-0023] — COMPUTED | aletheia.critic 1.0
- predicted claims out of domain: 0 [E-0024] — COMPUTED | aletheia.critic 1.0
- ledger claims total: 24 [E-0025] — COMPUTED | aletheia.critic 1.0
- fewer than two oracles scored the candidates; no consensus check possible

## Verification

- claims ledger: ledger coverage 100.0% (29/29 numeric tokens), 23/27 claims cited, 0 violation(s)
- answer blocked by verifier: **False**
- safety verdict: **ALLOW**

## Invariant checks

- result: **PASS**

## Trace

- run log: `runs/run-20261113T013351-3031f3.jsonl`
- structured answer: `runs/run-20261113T013351-3031f3.answer.json`
- wall time: 0.28 s, LLM calls: 3, tool calls: 72 (72 served from cache)
