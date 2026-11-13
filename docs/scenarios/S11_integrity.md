# S11 — Target/structure identity mismatch is blocked

*track: integrity · generated from run `run-20261113T013405-c8f150` on 2026-11-12T22:34:05 · pattern `supervisor` · LLM backend `replay/rules (offline)`*

## User request

> Analyse ABL1 kinase (P00519) using PDB structure 1M17 and dock imatinib into it.

## Expected answer (declared before the run)

The identity check finds that 1M17 is not cross-referenced to P00519, marks the mismatch, and blocks the structure-based steps instead of docking into the wrong protein.

## What the system planned

- intents: `protein_analysis, docking`
- planner: `callable+cache`
- agents invoked: `target_analyst`, `property_agent`
- tools called (11): `uniprot.entry`, `pubchem.compound_by_name`, `rdkit.standardize`, `chembl.target_by_accession`, `uniprot.sequence_features`, `alphafold.download_model`, `rdkit.descriptors`, `alphafold.plddt_summary`, `rdkit.druglikeness`, `rdkit.alerts`, `admet.profile`

## Actual result

### What the system did

Planner `callable+cache` routed this request to the intents protein_analysis, docking.

- `S1` **target_analyst** -> resolve_target — every downstream claim needs a verified target identity
- `S2` **property_agent** -> profile_molecules — descriptors and alerts for the molecules named by the user
- `S3` **docking_agent** -> dock — structure-based score, validated by redocking on the same receptor
- `S4` **structure_analyst** -> analyse_structure — binding-site detection on the selected structure
- `S5` **critic** -> cross_check — independent recomputation and applicability-domain audit

Tools actually invoked: `admet.profile`, `alphafold.download_model`, `alphafold.plddt_summary`, `chembl.target_by_accession`, `pubchem.compound_by_name`, `rdkit.alerts`, `rdkit.descriptors`, `rdkit.druglikeness`, `rdkit.standardize`, `uniprot.entry`, `uniprot.sequence_features`.

### Target

**ABL1** — Tyrosine-protein kinase ABL1 (Homo sapiens), UniProt `P00519`.
- Sequence length: 1130 residues [E-0002] — RETRIEVED | P00519 @ 2026-11-11
- Experimental structures cross-referenced: 85 [E-0003] — RETRIEVED | P00519 @ 2026-11-11
- ChEMBL target id: `CHEMBL1862` [E-0006] — RETRIEVED | CHEMBL1862 @ 2026-11-12
- No usable experimental structure; AlphaFold DB model `AF-P00519-F1` used, mean pLDDT 63.37 [E-0024] — COMPUTED | alphafold.plddt_summary afdb-api
- Target identity checks passed: 1 of 2 [E-0030] — uniprot_length_matches_sequence; pdb_belongs_to_accession

### Property profile — user:imatinib

`Cc1ccc(NC(=O)c2ccc(CN3CCN(C)CC3)cc2)cc1Nc1nccc(-c2cccnc2)n1`

- MW: 493.615 Da [E-0009] — COMPUTED | rdkit.descriptors 2026.09.2
- cLogP: 4.59  [E-0010] — COMPUTED | rdkit.descriptors 2026.09.2
- TPSA: 86.28 A^2 [E-0011] — COMPUTED | rdkit.descriptors 2026.09.2
- rotatable bonds: 7  [E-0014] — COMPUTED | rdkit.descriptors 2026.09.2
- H-bond donors: 2  [E-0012] — COMPUTED | rdkit.descriptors 2026.09.2
- H-bond acceptors: 7  [E-0013] — COMPUTED | rdkit.descriptors 2026.09.2
- heavy atoms: 37  [E-0017] — COMPUTED | rdkit.descriptors 2026.09.2
- QED: 0.389  [E-0022] — COMPUTED | rdkit.descriptors 2026.09.2
- SA score: 2.332  [E-0023] — COMPUTED | rdkit.descriptors 2026.09.2
- Ro5 violations: 0  [E-0025] — COMPUTED | rdkit.druglikeness 2026.09.2
- structural alerts: 0  [E-0026] — COMPUTED | rdkit.alerts 2026.09.2
- ESOL logS: -5.81 log10(mol/L) [E-0027] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- CNS-MPO-like: 2.956  [E-0028] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- structural alerts: liability:hERG-type basic amine with cLogP>3

### Degradations reported

- identity check failed: 1M17 is not cross-referenced to P00519; structure-based steps are blocked
- structure steps skipped: target identity checks did not pass
- step S3 (docking_agent) not executed: dependency ['S1'] failed
- step S4 (structure_analyst) not executed: dependency ['S1'] failed
- step S5 (critic) not executed: dependency ['S1', 'S3', 'S4'] failed

## Verification

- claims ledger: ledger coverage 100.0% (20/20 numeric tokens), 20/31 claims cited, 0 violation(s)
- answer blocked by verifier: **False**
- safety verdict: **ALLOW**

## Invariant checks

- result: **PASS**

## Trace

- run log: `runs/run-20261113T013405-c8f150.jsonl`
- structured answer: `runs/run-20261113T013405-c8f150.answer.json`
- wall time: 0.1 s, LLM calls: 3, tool calls: 11 (11 served from cache)
