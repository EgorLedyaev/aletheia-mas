# S02 — Structure selection and binding-site detection

*track: protein · generated from run `run-20261113T013350-fc0b00` on 2026-11-12T22:33:50 · pattern `supervisor` · LLM backend `replay/rules (offline)`*

## User request

> Analyse the structure of EGFR (P00533): pick a structure, find the binding site and tell me how confident the pocket detection is.

## Expected answer (declared before the run)

Picks a high-resolution X-ray entry with a bound ligand, runs the LIGSITE-style cavity detector and reports the distance from the detected cavity to the crystallographic ligand as a localisation check.

## What the system planned

- intents: `protein_analysis`
- planner: `callable+cache`
- agents invoked: `target_analyst`, `structure_analyst`, `critic`
- tools called (8): `uniprot.entry`, `chembl.target_by_accession`, `uniprot.sequence_features`, `pdb.download`, `pdb.ligands`, `pdb.entry`, `pdb.chain_sequences`, `pocket.detect`

## Actual result

### What the system did

Planner `callable+cache` routed this request to the intents protein_analysis.

- `S1` **target_analyst** -> resolve_target — every downstream claim needs a verified target identity
- `S2` **structure_analyst** -> analyse_structure — binding-site detection on the selected structure
- `S3` **critic** -> cross_check — independent recomputation and applicability-domain audit

Tools actually invoked: `chembl.target_by_accession`, `pdb.chain_sequences`, `pdb.download`, `pdb.entry`, `pdb.ligands`, `pocket.detect`, `uniprot.entry`, `uniprot.sequence_features`.

### Target

**EGFR** — Epidermal growth factor receptor (Homo sapiens), UniProt `P00533`.
- Sequence length: 1210 residues [E-0002] — RETRIEVED | P00533 @ 2026-11-11
- Experimental structures cross-referenced: 388 [E-0003] — RETRIEVED | P00533 @ 2026-11-11
- Structure selected: `8A27` at 1.07 A resolution [E-0007]
- Co-crystal ligand component id: `KY9` [E-0009] — COMPUTED | pdb.ligands rcsb-rest-v1
- ChEMBL target id: `CHEMBL203` [E-0004] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Target identity checks passed: 2 of 2 [E-0018] — uniprot_length_matches_sequence; structure_sequence_matches_uniprot

### Binding site

- top pocket volume: 445 A^3 [E-0010] — COMPUTED | pocket.detect ligsite-like-1.0
- n pockets detected: 3  [E-0011] — COMPUTED | pocket.detect ligsite-like-1.0
- pocket to cocrystal distance: 0.44 A [E-0012] — COMPUTED | pocket.detect ligsite-like-1.0
- localisation check: the detected cavity nearest the crystallographic ligand centroid is pocket rank 1, within 5 A of it

### Independent cross-check

- critic claims recomputed: 0 [E-0013] — COMPUTED | aletheia.critic 1.0
- critic recomputation mismatches: 0 [E-0014] — COMPUTED | aletheia.critic 1.0
- predicted claims total: 0 [E-0015] — COMPUTED | aletheia.critic 1.0
- predicted claims out of domain: 0 [E-0016] — COMPUTED | aletheia.critic 1.0
- ledger claims total: 16 [E-0017] — COMPUTED | aletheia.critic 1.0
- fewer than two oracles scored the candidates; no consensus check possible

## Verification

- claims ledger: ledger coverage 100.0% (22/22 numeric tokens), 16/19 claims cited, 0 violation(s)
- answer blocked by verifier: **False**
- safety verdict: **ALLOW**

## Invariant checks

- result: **PASS**

## Trace

- run log: `runs/run-20261113T013350-fc0b00.jsonl`
- structured answer: `runs/run-20261113T013350-fc0b00.answer.json`
- wall time: 0.08 s, LLM calls: 3, tool calls: 8 (8 served from cache)
