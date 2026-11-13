# S05b — Degradation path: the same receptor, the oracle that fails

*track: protein · generated from run `run-20261113T013351-261b4d` on 2026-11-12T22:33:51 · pattern `supervisor` · LLM backend `replay/rules (offline)`*

## User request

> Dock erlotinib (C#Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1) into the EGFR structure 1M17 using the default Vina scoring function and tell me whether that score can rank candidates.

## Expected answer (declared before the run)

Same receptor, same ligand, same box -- the other scoring function. Its measured enrichment on 1M17 (ROC AUC 0.632, 95% CI [0.479, 0.769]) does not clear chance, so the run must still publish the score, attach the failed enrichment to it, emit a degradation saying the score cannot order candidates, and withhold the ranking claim.

## What the system planned

- intents: `docking, rank_candidates`
- planner: `callable+cache`
- agents invoked: `target_analyst`, `property_agent`, `chemistry_retriever`, `docking_agent`, `structure_analyst`, `ranker`, `critic`
- tools called (106): `uniprot.search_gene`, `pubchem.compound_by_name`, `uniprot.entry`, `rdkit.standardize`, `chembl.target_by_accession`, `rdkit.descriptors`, `uniprot.sequence_features`, `rdkit.druglikeness`, `pdb.download`, `rdkit.alerts`, `pdb.ligands`, `admet.profile`, `pdb.entry`, `pdb.chain_sequences`, `pdb.extract_receptor`, `chembl.status`, `pocket.detect`, `docking.prepare_receptor`, `pdb.extract_ligand`, `chembl.activities`, `docking.box_from_ligand_pdb`, `rdkit.scaffold`, `docking.vina_version`, `pdb.chemcomp`, `docking.prepare_ligand`, `docking.vina_dock`, `docking.pose_rmsd_all_models`, `docking.contacts`, `ranking.pareto_front`, `ranking.butina_clusters`, `ranking.portfolio`

## Actual result

### What the system did

Planner `callable+cache` routed this request to the intents docking, rank_candidates.

- `S1` **target_analyst** -> resolve_target — every downstream claim needs a verified target identity
- `S2` **chemistry_retriever** -> known_actives — ground design in measured actives, not in LLM memory
- `S3` **property_agent** -> profile_molecules — descriptors and alerts for the molecules named by the user
- `S4` **docking_agent** -> dock — structure-based score, validated by redocking on the same receptor
- `S5` **structure_analyst** -> analyse_structure — binding-site detection on the selected structure
- `S6` **ranker** -> rank_and_select — multi-objective Pareto ranking + diversity-aware portfolio
- `S7` **critic** -> cross_check — independent recomputation and applicability-domain audit

Tools actually invoked: `admet.profile`, `chembl.activities`, `chembl.status`, `chembl.target_by_accession`, `docking.box_from_ligand_pdb`, `docking.contacts`, `docking.pose_rmsd_all_models`, `docking.prepare_ligand`, `docking.prepare_receptor`, `docking.vina_dock`, `docking.vina_version`, `pdb.chain_sequences`, `pdb.chemcomp`, `pdb.download`, `pdb.entry`, `pdb.extract_ligand`, `pdb.extract_receptor`, `pdb.ligands`, `pocket.detect`, `pubchem.compound_by_name`, `ranking.butina_clusters`, `ranking.pareto_front`, `ranking.portfolio`, `rdkit.alerts`, `rdkit.descriptors`, `rdkit.druglikeness`, `rdkit.scaffold`, `rdkit.standardize`, `uniprot.entry`, `uniprot.search_gene`, `uniprot.sequence_features`.

### Target

**EGFR** — Epidermal growth factor receptor (Homo sapiens), UniProt `P00533`.
- Sequence length: 1210 residues [E-0004] — RETRIEVED | P00533 @ 2026-11-11
- Experimental structures cross-referenced: 388 [E-0005] — RETRIEVED | P00533 @ 2026-11-11
- Structure selected: `1M17` at 2.6 A resolution [E-0030]
- Co-crystal ligand component id: `AQ4` [E-0033] — COMPUTED | pdb.ligands rcsb-rest-v1
- ChEMBL target id: `CHEMBL203` [E-0007] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Target identity checks passed: 3 of 3 [E-0081] — uniprot_length_matches_sequence; pdb_belongs_to_accession; structure_sequence_matches_uniprot

### Known chemistry (retrieved, not generated)

- ChEMBL release: ChEMBL_37 [E-0054] — RETRIEVED | ChEMBL ChEMBL_37 @ 2026-11-11
- ChEMBL target: CHEMBL203 [E-0058] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Unique actives retrieved: 271 [E-0059] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Median pChEMBL of retrieved actives: 6.72 [E-0060] — COMPUTED | chembl.activities ws-2.x
- Best pChEMBL of retrieved actives: 10.6 [E-0061] — COMPUTED | chembl.activities ws-2.x
- Most potent retrieved compound: CHEMBL29197 [E-0062] — RETRIEVED | CHEMBL29197 @ 2026-11-11

### Binding site

- top pocket volume: 458 A^3 [E-0055] — COMPUTED | pocket.detect ligsite-like-1.0
- n pockets detected: 4  [E-0056] — COMPUTED | pocket.detect ligsite-like-1.0
- pocket to cocrystal distance: 0.31 A [E-0057] — COMPUTED | pocket.detect ligsite-like-1.0
- localisation check: the detected cavity nearest the crystallographic ligand centroid is pocket rank 1, within 5 A of it

### Docking

- redocking rmsd top1: 4.188 A [E-0063] — COMPUTED | docking.pose_rmsd_all_models vina-1.2.7+obabel — validation: success_threshold_A=2.0, exhaustiveness=24, scoring_function=vina
- redocking rmsd best of modes: 1.361 A [E-0064] — COMPUTED | docking.pose_rmsd_all_models vina-1.2.7+obabel — validation: best_rmsd_rank=3, n_poses=9, scoring_function=vina
- docking enrichment roc auc: 0.632  [E-0065] — COMPUTED | aletheia.docking_validation 1.0 — validation: roc_auc=0.632, auc_ci95=[0.4794, 0.7695], ef_10pct=0.726, score_gap=-0.294, n_actives=28, n_decoys=33, decoy_class=measured inactive (pChEMBL <= 5), scoring_function=vina, usable_for_ranking=False, ordering_inverted=False, discriminates=False, source=eval/docking_benchmark.json (scripts/bench_docking.py, measured inactives)
- vina score: -7.048 kcal/mol [E-0066] — COMPUTED | docking.vina_dock vina-1.2.7+obabel — validation: ligand=AQ4, redock_rmsd_A=4.188, passes=False
- best vina score: -7.048 kcal/mol [E-0068] — COMPUTED | aletheia.docking_agent 1.0

### Ranking and portfolio

- pareto front size: 2 [E-0070] — COMPUTED | ranking.pareto_front 1.0
- n chemotype clusters: 1 [E-0071] — COMPUTED | ranking.butina_clusters 1.0
- portfolio size: 2 [E-0072] — COMPUTED | ranking.portfolio 1.0
- probability that the portfolio contains at least one hit: **withheld** [E-0073, E-0074, E-0075] — the hit-probability calibrator fails its pre-registered calibration criterion on the held-out scaffold-split test fold, so the value is kept as a ledger diagnostic rather than published (docs/preregistration.md, figures/calibration.png)

### Property profile — user:erlotinib

`C#Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1`

- MW: 393.443 Da [E-0008] — COMPUTED | rdkit.descriptors 2026.09.2
- cLogP: 3.405  [E-0009] — COMPUTED | rdkit.descriptors 2026.09.2
- TPSA: 74.73 A^2 [E-0010] — COMPUTED | rdkit.descriptors 2026.09.2
- rotatable bonds: 10  [E-0013] — COMPUTED | rdkit.descriptors 2026.09.2
- H-bond donors: 1  [E-0011] — COMPUTED | rdkit.descriptors 2026.09.2
- H-bond acceptors: 7  [E-0012] — COMPUTED | rdkit.descriptors 2026.09.2
- heavy atoms: 29  [E-0016] — COMPUTED | rdkit.descriptors 2026.09.2
- QED: 0.418  [E-0021] — COMPUTED | rdkit.descriptors 2026.09.2
- SA score: 2.478  [E-0022] — COMPUTED | rdkit.descriptors 2026.09.2
- Ro5 violations: 0  [E-0025] — COMPUTED | rdkit.druglikeness 2026.09.2
- structural alerts: 2  [E-0026] — COMPUTED | rdkit.alerts 2026.09.2
- ESOL logS: -4.173 log10(mol/L) [E-0027] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- CNS-MPO-like: 5.188  [E-0028] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- structural alerts: BRENK:Aliphatic_long_chain; BRENK:triple_bond

### Property profile — user:C#Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1

`C#Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1`

- MW: 393.443 Da [E-0034] — COMPUTED | rdkit.descriptors 2026.09.2
- cLogP: 3.405  [E-0035] — COMPUTED | rdkit.descriptors 2026.09.2
- TPSA: 74.73 A^2 [E-0036] — COMPUTED | rdkit.descriptors 2026.09.2
- rotatable bonds: 10  [E-0039] — COMPUTED | rdkit.descriptors 2026.09.2
- H-bond donors: 1  [E-0037] — COMPUTED | rdkit.descriptors 2026.09.2
- H-bond acceptors: 7  [E-0038] — COMPUTED | rdkit.descriptors 2026.09.2
- heavy atoms: 29  [E-0042] — COMPUTED | rdkit.descriptors 2026.09.2
- QED: 0.418  [E-0047] — COMPUTED | rdkit.descriptors 2026.09.2
- SA score: 2.478  [E-0048] — COMPUTED | rdkit.descriptors 2026.09.2
- Ro5 violations: 0  [E-0049] — COMPUTED | rdkit.druglikeness 2026.09.2
- structural alerts: 2  [E-0050] — COMPUTED | rdkit.alerts 2026.09.2
- ESOL logS: -4.173 log10(mol/L) [E-0051] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- CNS-MPO-like: 5.188  [E-0052] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- structural alerts: BRENK:Aliphatic_long_chain; BRENK:triple_bond

### Independent cross-check

- critic claims recomputed: 8 [E-0076] — COMPUTED | aletheia.critic 1.0
- critic recomputation mismatches: 0 [E-0077] — COMPUTED | aletheia.critic 1.0
- predicted claims total: 7 [E-0078] — COMPUTED | aletheia.critic 1.0
- predicted claims out of domain: 0 [E-0079] — COMPUTED | aletheia.critic 1.0
- ledger claims total: 79 [E-0080] — COMPUTED | aletheia.critic 1.0
- 7 predicted value(s) have no applicability-domain verdict and are reported as such
- fewer than two oracles scored the candidates; no consensus check possible

### Degradations reported

- on 1M17 the vina setup does not separate actives from measured inactives (ROC AUC 0.632, 95% CI [0.4794, 0.7695]); the scores below are geometry-driven numbers and must not be read as a potency ranking, and ranking on this oracle is disabled
- redocking did not reproduce the crystal pose at rank 1 (top-1 RMSD 4.188 A); near-native pose was sampled but not ranked first: a scoring-function failure, not a search failure
- vina_score excluded from the ranking objectives: its enrichment on this receptor does not pass the pre-registered criterion; it is reported but does not order candidates

## Verification

- claims ledger: ledger coverage 100.0% (87/87 numeric tokens), 60/82 claims cited, 0 violation(s)
- answer blocked by verifier: **False**
- safety verdict: **ALLOW**

## Invariant checks

- result: **PASS**

## Trace

- run log: `runs/run-20261113T013351-261b4d.jsonl`
- structured answer: `runs/run-20261113T013351-261b4d.answer.json`
- wall time: 0.57 s, LLM calls: 3, tool calls: 106 (98 served from cache)
