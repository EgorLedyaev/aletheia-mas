# S05 — Docking with the oracle that passes validation

*track: protein · generated from run `run-20261113T013351-e45b49` on 2026-11-12T22:33:51 · pattern `supervisor` · LLM backend `replay/rules (offline)`*

## User request

> Dock erlotinib (C#Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1) into the EGFR structure 1M17 using the Vinardo scoring function and validate the docking by redocking the co-crystal ligand.

## Expected answer (declared before the run)

Prepares receptor and ligand, docks with the scoring function whose measured enrichment on THIS receptor passes the pre-registered criterion (Vinardo on 1M17: ROC AUC 0.734, 95% CI [0.601, 0.852]), re-docks the co-crystal ligand at validation-grade exhaustiveness, reports BOTH the top-1 and the best-of-modes RMSD, the measured enrichment for this receptor/oracle pair, and the contacting residues.

## What the system planned

- intents: `docking`
- planner: `callable+cache`
- agents invoked: `target_analyst`, `property_agent`, `docking_agent`, `structure_analyst`, `critic`
- tools called (34): `uniprot.search_gene`, `rdkit.standardize`, `uniprot.entry`, `chembl.target_by_accession`, `uniprot.sequence_features`, `rdkit.descriptors`, `pdb.download`, `rdkit.druglikeness`, `pdb.ligands`, `rdkit.alerts`, `pdb.entry`, `admet.profile`, `pdb.chain_sequences`, `pdb.extract_receptor`, `pocket.detect`, `docking.prepare_receptor`, `pdb.extract_ligand`, `docking.box_from_ligand_pdb`, `docking.vina_version`, `pdb.chemcomp`, `docking.prepare_ligand`, `docking.vina_dock`, `docking.pose_rmsd_all_models`, `docking.contacts`

## Actual result

### What the system did

Planner `callable+cache` routed this request to the intents docking.

- `S1` **target_analyst** -> resolve_target — every downstream claim needs a verified target identity
- `S2` **property_agent** -> profile_molecules — descriptors and alerts for the molecules named by the user
- `S3` **docking_agent** -> dock — structure-based score, validated by redocking on the same receptor
- `S4` **structure_analyst** -> analyse_structure — binding-site detection on the selected structure
- `S5` **critic** -> cross_check — independent recomputation and applicability-domain audit

Tools actually invoked: `admet.profile`, `chembl.target_by_accession`, `docking.box_from_ligand_pdb`, `docking.contacts`, `docking.pose_rmsd_all_models`, `docking.prepare_ligand`, `docking.prepare_receptor`, `docking.vina_dock`, `docking.vina_version`, `pdb.chain_sequences`, `pdb.chemcomp`, `pdb.download`, `pdb.entry`, `pdb.extract_ligand`, `pdb.extract_receptor`, `pdb.ligands`, `pocket.detect`, `rdkit.alerts`, `rdkit.descriptors`, `rdkit.druglikeness`, `rdkit.standardize`, `uniprot.entry`, `uniprot.search_gene`, `uniprot.sequence_features`.

### Target

**EGFR** — Epidermal growth factor receptor (Homo sapiens), UniProt `P00533`.
- Sequence length: 1210 residues [E-0004] — RETRIEVED | P00533 @ 2026-11-11
- Experimental structures cross-referenced: 388 [E-0005] — RETRIEVED | P00533 @ 2026-11-11
- Structure selected: `1M17` at 2.6 A resolution [E-0026]
- Co-crystal ligand component id: `AQ4` [E-0031] — COMPUTED | pdb.ligands rcsb-rest-v1
- ChEMBL target id: `CHEMBL203` [E-0006] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Target identity checks passed: 3 of 3 [E-0046] — uniprot_length_matches_sequence; pdb_belongs_to_accession; structure_sequence_matches_uniprot

### Binding site

- top pocket volume: 458 A^3 [E-0032] — COMPUTED | pocket.detect ligsite-like-1.0
- n pockets detected: 4  [E-0033] — COMPUTED | pocket.detect ligsite-like-1.0
- pocket to cocrystal distance: 0.31 A [E-0034] — COMPUTED | pocket.detect ligsite-like-1.0
- localisation check: the detected cavity nearest the crystallographic ligand centroid is pocket rank 1, within 5 A of it

### Docking

- redocking rmsd top1: 2.685 A [E-0035] — COMPUTED | docking.pose_rmsd_all_models vina-1.2.7+obabel — validation: success_threshold_A=2.0, exhaustiveness=24, scoring_function=vinardo
- redocking rmsd best of modes: 1.23 A [E-0036] — COMPUTED | docking.pose_rmsd_all_models vina-1.2.7+obabel — validation: best_rmsd_rank=8, n_poses=9, scoring_function=vinardo
- docking enrichment roc auc: 0.734  [E-0037] — COMPUTED | aletheia.docking_validation 1.0 — validation: roc_auc=0.7338, auc_ci95=[0.6006, 0.8517], ef_10pct=0.0, score_gap=-0.497, n_actives=28, n_decoys=33, decoy_class=measured inactive (pChEMBL <= 5), scoring_function=vinardo, usable_for_ranking=True, ordering_inverted=False, discriminates=True, source=eval/docking_benchmark.json (scripts/bench_docking.py, measured inactives)
- vina score: -4.945 kcal/mol [E-0038] — COMPUTED | docking.vina_dock vina-1.2.7+obabel — validation: ligand=AQ4, redock_rmsd_A=2.685, passes=False
- best vina score: -4.945 kcal/mol [E-0040] — COMPUTED | aletheia.docking_agent 1.0

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
- ESOL logS: -4.173 log10(mol/L) [E-0027] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- CNS-MPO-like: 5.188  [E-0028] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- structural alerts: BRENK:Aliphatic_long_chain; BRENK:triple_bond

### Independent cross-check

- critic claims recomputed: 8 [E-0041] — COMPUTED | aletheia.critic 1.0
- critic recomputation mismatches: 0 [E-0042] — COMPUTED | aletheia.critic 1.0
- predicted claims total: 2 [E-0043] — COMPUTED | aletheia.critic 1.0
- predicted claims out of domain: 0 [E-0044] — COMPUTED | aletheia.critic 1.0
- ledger claims total: 44 [E-0045] — COMPUTED | aletheia.critic 1.0
- 2 predicted value(s) have no applicability-domain verdict and are reported as such
- fewer than two oracles scored the candidates; no consensus check possible

### Degradations reported

- redocking did not reproduce the crystal pose at rank 1 (top-1 RMSD 2.685 A); near-native pose was sampled but not ranked first: a scoring-function failure, not a search failure

## Verification

- claims ledger: ledger coverage 100.0% (61/61 numeric tokens), 34/47 claims cited, 0 violation(s)
- answer blocked by verifier: **False**
- safety verdict: **ALLOW**

## Invariant checks

- result: **PASS**

## Trace

- run log: `runs/run-20261113T013351-e45b49.jsonl`
- structured answer: `runs/run-20261113T013351-e45b49.answer.json`
- wall time: 0.31 s, LLM calls: 3, tool calls: 34 (26 served from cache)
