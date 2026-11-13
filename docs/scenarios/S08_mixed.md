# S08 — Full end-to-end campaign

*track: mixed · generated from run `run-20261113T013401-4077d6` on 2026-11-12T22:34:01 · pattern `supervisor` · LLM backend `replay/rules (offline)`*

## User request

> Run a full hit-finding campaign against EGFR: retrieve known actives, generate new candidates, model activity, dock the best ones and give me a ranked shortlist with a portfolio.

## Expected answer (declared before the run)

Executes the whole funnel -- target, actives, generation, cheap gate, QSAR, docking with redocking validation, Pareto ranking and portfolio selection -- and reports P(>=1 hit) under two correlation assumptions.

## What the system planned

- intents: `full_campaign, ligand_lookup, generate_analogs, qsar, docking, rank_candidates`
- planner: `callable+cache`
- agents invoked: `target_analyst`, `chemistry_retriever`, `structure_analyst`, `molecule_generator`, `property_agent`, `qsar_agent`, `docking_agent`, `ranker`, `critic`
- tools called (761): `uniprot.search_gene`, `uniprot.entry`, `chembl.target_by_accession`, `uniprot.sequence_features`, `pdb.download`, `pdb.ligands`, `pdb.entry`, `pdb.chain_sequences`, `chembl.status`, `pocket.detect`, `chembl.activities`, `rdkit.scaffold`, `generators.rule_decorate`, `generators.selfies_mutate`, `generators.validate_proposals`, `generators.brics_recombine`, `rdkit.validate_batch`, `generators.novelty`, `hazard.screen_batch`, `rdkit.standardize`, `rdkit.descriptors`, `rdkit.druglikeness`, `rdkit.alerts`, `admet.profile`, `qsar.fit`, `pdb.extract_receptor`, `docking.prepare_receptor`, `qsar.predict`, `pdb.extract_ligand`, `docking.box_from_ligand_pdb`, `docking.vina_version`, `pdb.chemcomp`, `docking.prepare_ligand`, `docking.vina_dock`, `docking.pose_rmsd_all_models`, `docking.contacts`, `ranking.pareto_front`, `ranking.butina_clusters`, `ranking.portfolio`

## Actual result

### What the system did

Planner `callable+cache` routed this request to the intents full_campaign, ligand_lookup, generate_analogs, qsar, docking, rank_candidates.

- `S1` **target_analyst** -> resolve_target — every downstream claim needs a verified target identity
- `S2` **chemistry_retriever** -> known_actives — ground design in measured actives, not in LLM memory
- `S3` **molecule_generator** -> generate — three independent generators limit single-model bias
- `S4` **property_agent** -> profile_candidates — cheap filters before any expensive oracle (funnel gate 1)
- `S5` **qsar_agent** -> fit_and_predict — scaffold-split activity proxy with baselines and conformal intervals
- `S6` **docking_agent** -> dock — structure-based score, validated by redocking on the same receptor
- `S7` **structure_analyst** -> analyse_structure — binding-site detection on the selected structure
- `S8` **ranker** -> rank_and_select — multi-objective Pareto ranking + diversity-aware portfolio
- `S9` **critic** -> cross_check — independent recomputation and applicability-domain audit

Tools actually invoked: `admet.profile`, `chembl.activities`, `chembl.status`, `chembl.target_by_accession`, `docking.box_from_ligand_pdb`, `docking.contacts`, `docking.pose_rmsd_all_models`, `docking.prepare_ligand`, `docking.prepare_receptor`, `docking.vina_dock`, `docking.vina_version`, `generators.brics_recombine`, `generators.novelty`, `generators.rule_decorate`, `generators.selfies_mutate`, `generators.validate_proposals`, `hazard.screen_batch`, `pdb.chain_sequences`, `pdb.chemcomp`, `pdb.download`, `pdb.entry`, `pdb.extract_ligand`, `pdb.extract_receptor`, `pdb.ligands`, `pocket.detect`, `qsar.fit`, `qsar.predict`, `ranking.butina_clusters`, `ranking.pareto_front`, `ranking.portfolio`, `rdkit.alerts`, `rdkit.descriptors`, `rdkit.druglikeness`, `rdkit.scaffold`, `rdkit.standardize`, `rdkit.validate_batch`, `uniprot.entry`, `uniprot.search_gene`, `uniprot.sequence_features`.

### Target

**EGFR** — Epidermal growth factor receptor (Homo sapiens), UniProt `P00533`.
- Sequence length: 1210 residues [E-0003] — RETRIEVED | P00533 @ 2026-11-11
- Experimental structures cross-referenced: 388 [E-0004] — RETRIEVED | P00533 @ 2026-11-11
- Structure selected: `8A27` at 1.07 A resolution [E-0008]
- Co-crystal ligand component id: `KY9` [E-0010] — COMPUTED | pdb.ligands rcsb-rest-v1
- ChEMBL target id: `CHEMBL203` [E-0005] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Target identity checks passed: 2 of 2 [E-2839] — uniprot_length_matches_sequence; structure_sequence_matches_uniprot

### Known chemistry (retrieved, not generated)

- ChEMBL release: ChEMBL_37 [E-0011] — RETRIEVED | ChEMBL ChEMBL_37 @ 2026-11-11
- ChEMBL target: CHEMBL203 [E-0015] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Unique actives retrieved: 271 [E-0016] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Median pChEMBL of retrieved actives: 6.72 [E-0017] — COMPUTED | chembl.activities ws-2.x
- Best pChEMBL of retrieved actives: 10.6 [E-0018] — COMPUTED | chembl.activities ws-2.x
- Most potent retrieved compound: CHEMBL29197 [E-0019] — RETRIEVED | CHEMBL29197 @ 2026-11-11

### Generation

- llm edit validity: 0.9 [E-0021] — COMPUTED | generators.validate_proposals 1.0
- G1 rule decorate n generated: 37 [E-0022] — COMPUTED | rdkit.validate_batch 2026.09.2
- G1 rule decorate frac novel: 0 [E-0023] — COMPUTED | generators.novelty 1.0
- G1 rule decorate mean max similarity: 0.646 [E-0024] — COMPUTED | generators.novelty 1.0
- G3 selfies mutate n generated: 40 [E-0025] — COMPUTED | rdkit.validate_batch 2026.09.2
- G3 selfies mutate frac novel: 0.625 [E-0026] — COMPUTED | generators.novelty 1.0
- G3 selfies mutate mean max similarity: 0.335 [E-0027] — COMPUTED | generators.novelty 1.0
- G4 llm edits n generated: 9 [E-0028] — COMPUTED | rdkit.validate_batch 2026.09.2
- G4 llm edits frac novel: 0 [E-0029] — COMPUTED | generators.novelty 1.0
- G4 llm edits mean max similarity: 0.778 [E-0030] — COMPUTED | generators.novelty 1.0
- G2 brics recombine n generated: 40 [E-0031] — COMPUTED | rdkit.validate_batch 2026.09.2
- G2 brics recombine frac novel: 0.075 [E-0032] — COMPUTED | generators.novelty 1.0
- G2 brics recombine mean max similarity: 0.449 [E-0033] — COMPUTED | generators.novelty 1.0
- hazard screened structures: 126 [E-0034] — COMPUTED | hazard.screen_batch 1.0
- candidates after dedup and safety: 126 [E-0035] — COMPUTED | aletheia.generator 1.0

### Binding site

- top pocket volume: 445 A^3 [E-0012] — COMPUTED | pocket.detect ligsite-like-1.0
- n pockets detected: 3  [E-0013] — COMPUTED | pocket.detect ligsite-like-1.0
- pocket to cocrystal distance: 0.44 A [E-0014] — COMPUTED | pocket.detect ligsite-like-1.0
- localisation check: the detected cavity nearest the crystallographic ligand centroid is pocket rank 1, within 5 A of it

### Docking

- redocking rmsd top1: 1.881 A [E-2797] — COMPUTED | docking.pose_rmsd_all_models vina-1.2.7+obabel — validation: success_threshold_A=2.0, exhaustiveness=24, scoring_function=vina
- redocking rmsd best of modes: 0.933 A [E-2798] — COMPUTED | docking.pose_rmsd_all_models vina-1.2.7+obabel — validation: best_rmsd_rank=2, n_poses=8, scoring_function=vina
- docking enrichment roc auc: 0.593  [E-2799] — COMPUTED | aletheia.docking_validation 1.0 — validation: roc_auc=0.5931, auc_ci95=[0.4416, 0.7392], ef_10pct=0.726, score_gap=-0.191, n_actives=28, n_decoys=33, decoy_class=measured inactive (pChEMBL <= 5), scoring_function=vina, usable_for_ranking=False, ordering_inverted=False, discriminates=False, source=eval/docking_benchmark.json (scripts/bench_docking.py, measured inactives)
- vina score: -7.958 kcal/mol [E-2800] — COMPUTED | docking.vina_dock vina-1.2.7+obabel — validation: ligand=KY9, redock_rmsd_A=1.881, passes=True
- vina score: -9.017 kcal/mol [E-2802] — COMPUTED | docking.vina_dock vina-1.2.7+obabel — validation: ligand=KY9, redock_rmsd_A=1.881, passes=True
- vina score: -7.859 kcal/mol [E-2804] — COMPUTED | docking.vina_dock vina-1.2.7+obabel — validation: ligand=KY9, redock_rmsd_A=1.881, passes=True
- vina score: -8.189 kcal/mol [E-2806] — COMPUTED | docking.vina_dock vina-1.2.7+obabel — validation: ligand=KY9, redock_rmsd_A=1.881, passes=True
- vina score: -8.133 kcal/mol [E-2808] — COMPUTED | docking.vina_dock vina-1.2.7+obabel — validation: ligand=KY9, redock_rmsd_A=1.881, passes=True
- vina score: -8.27 kcal/mol [E-2810] — COMPUTED | docking.vina_dock vina-1.2.7+obabel — validation: ligand=KY9, redock_rmsd_A=1.881, passes=True
- vina score: -6.454 kcal/mol [E-2812] — COMPUTED | docking.vina_dock vina-1.2.7+obabel — validation: ligand=KY9, redock_rmsd_A=1.881, passes=True
- vina score: -8.311 kcal/mol [E-2814] — COMPUTED | docking.vina_dock vina-1.2.7+obabel — validation: ligand=KY9, redock_rmsd_A=1.881, passes=True
- best vina score: -9.017 kcal/mol [E-2816] — COMPUTED | aletheia.docking_agent 1.0

### Activity model

- qsar test rmse: 0.85 [E-2684] — COMPUTED | qsar.fit 1.0
- qsar test spearman: 0.339 [E-2685] — COMPUTED | qsar.fit 1.0
- qsar baseline mean rmse: 1.73 [E-2686] — COMPUTED | qsar.fit 1.0
- qsar baseline 1nn rmse: 0.972 [E-2687] — COMPUTED | qsar.fit 1.0
- qsar n training records: 174 [E-2688] — COMPUTED | qsar.fit 1.0
- qsar conformal empirical coverage: 0.944 [E-2689] — COMPUTED | qsar.fit 1.0
- qsar baseline verdict: model beats both baselines [E-2690] — COMPUTED | qsar.fit 1.0
- qsar candidates scored: 104 [E-2795] — COMPUTED | qsar.predict 1.0
- qsar candidates out of domain: 11 [E-2796] — COMPUTED | qsar.predict 1.0

### Ranking and portfolio

- pareto front size: 8 [E-2817] — COMPUTED | ranking.pareto_front 1.0
- n chemotype clusters: 38 [E-2818] — COMPUTED | ranking.butina_clusters 1.0
- portfolio size: 8 [E-2819] — COMPUTED | ranking.portfolio 1.0
- oracle disagreement spearman: 0.071 [E-2823] — COMPUTED | ranking.portfolio 1.0
- probability that the portfolio contains at least one hit: **withheld** [E-2820, E-2821, E-2822] — the hit-probability calibrator fails its pre-registered calibration criterion on the held-out scaffold-split test fold, so the value is kept as a ledger diagnostic rather than published (docs/preregistration.md, figures/calibration.png)

### Independent cross-check

- critic claims recomputed: 8 [E-2824] — COMPUTED | aletheia.critic 1.0
- critic recomputation mismatches: 0 [E-2825] — COMPUTED | aletheia.critic 1.0
- predicted claims total: 359 [E-2826] — COMPUTED | aletheia.critic 1.0
- predicted claims out of domain: 11 [E-2827] — COMPUTED | aletheia.critic 1.0
- oracle rank correlation qsar lower vs qsar max tanimoto to train: 0.874 [E-2828] — COMPUTED | scipy.stats.spearmanr 1.0
- oracle rank correlation qsar lower vs qsar pchembl: 1 [E-2829] — COMPUTED | scipy.stats.spearmanr 1.0
- oracle rank correlation qsar lower vs qsar upper: 1 [E-2830] — COMPUTED | scipy.stats.spearmanr 1.0
- oracle rank correlation qsar lower vs vina score: 0.071 [E-2831] — COMPUTED | scipy.stats.spearmanr 1.0
- oracle rank correlation qsar max tanimoto to train vs qsar pchembl: 0.874 [E-2832] — COMPUTED | scipy.stats.spearmanr 1.0
- oracle rank correlation qsar max tanimoto to train vs qsar upper: 0.874 [E-2833] — COMPUTED | scipy.stats.spearmanr 1.0
- oracle rank correlation qsar max tanimoto to train vs vina score: -0.286 [E-2834] — COMPUTED | scipy.stats.spearmanr 1.0
- oracle rank correlation qsar pchembl vs qsar upper: 1 [E-2835] — COMPUTED | scipy.stats.spearmanr 1.0
- oracle rank correlation qsar pchembl vs vina score: 0.071 [E-2836] — COMPUTED | scipy.stats.spearmanr 1.0
- oracle rank correlation qsar upper vs vina score: 0.071 [E-2837] — COMPUTED | scipy.stats.spearmanr 1.0
- ledger claims total: 2837 [E-2838] — COMPUTED | aletheia.critic 1.0
- 255 predicted value(s) have no applicability-domain verdict and are reported as such
- oracles 'qsar_lower' and 'vina_score' barely agree (rho=0.071); the ranking should not be read as a consensus
- oracles 'qsar_pchembl' and 'vina_score' barely agree (rho=0.071); the ranking should not be read as a consensus
- oracles 'qsar_upper' and 'vina_score' barely agree (rho=0.071); the ranking should not be read as a consensus

### Degradations reported

- on 8A27 the vina setup does not separate actives from measured inactives (ROC AUC 0.5931, 95% CI [0.4416, 0.7392]); the scores below are geometry-driven numbers and must not be read as a potency ranking, and ranking on this oracle is disabled
- vina_score excluded from the ranking objectives: its enrichment on this receptor does not pass the pre-registered criterion; it is reported but does not order candidates

## Verification

- claims ledger: ledger coverage 100.0% (146/146 numeric tokens), 76/2840 claims cited, 0 violation(s)
- answer blocked by verifier: **False**
- safety verdict: **ALLOW**

## Invariant checks

- result: **PASS**

## Trace

- run log: `runs/run-20261113T013401-4077d6.jsonl`
- structured answer: `runs/run-20261113T013401-4077d6.answer.json`
- wall time: 4.16 s, LLM calls: 4, tool calls: 761 (753 served from cache)
