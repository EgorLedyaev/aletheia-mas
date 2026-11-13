# Aletheia answer

**Request:** Give me a brief on the EGFR kinase target: what is known, which structures exist, and what are the most potent known inhibitors in ChEMBL?

*run `run-20261111T211737-5a6654` · source `cached` · 4.8s · planner `callable+cache` · intents target_brief, protein_analysis, ligand_lookup*

## What the system did

Planner `callable+cache` routed this request to the intents target_brief, protein_analysis, ligand_lookup.

- `S1` **target_analyst** -> resolve_target — every downstream claim needs a verified target identity
- `S2` **chemistry_retriever** -> known_actives — ground design in measured actives, not in LLM memory
- `S3` **target_analyst** -> analyse_structure — sequence/structure features and pocket definition
- `S4` **critic** -> cross_check — independent recomputation and applicability-domain audit

Tools actually invoked: `chembl.activities`, `chembl.status`, `chembl.target_by_accession`, `pdb.chain_sequences`, `pdb.download`, `pdb.entry`, `pdb.ligands`, `rdkit.scaffold`, `uniprot.entry`, `uniprot.search_gene`, `uniprot.sequence_features`.

## Target

**EGFR** — Epidermal growth factor receptor (Homo sapiens), UniProt `P00533`.
- Sequence length: 1210 residues [E-0014] — RETRIEVED | P00533 @ 2026-11-11
- Experimental structures cross-referenced: 388 [E-0015] — RETRIEVED | P00533 @ 2026-11-11
- Structure selected: `8A27` at 1.07 A resolution [E-0022]
- Target identity checks passed: 2 of 2 [E-0031] — uniprot_length_matches_sequence; structure_sequence_matches_uniprot

<sub>claims: E-0013, E-0014, E-0015, E-0022, E-0022, E-0031, E-0032</sub>

## Known chemistry (retrieved, not generated)

- ChEMBL release: ChEMBL_37 [E-0010] — RETRIEVED | ChEMBL ChEMBL_37 @ 2026-11-11
- ChEMBL target: CHEMBL203 [E-0012] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Unique actives retrieved: 271 [E-0016] — RETRIEVED | CHEMBL203 @ 2026-11-11
- Median pChEMBL of retrieved actives: 6.72 [E-0017] — COMPUTED | chembl.activities ws-2.x
- Best pChEMBL of retrieved actives: 10.6 [E-0018] — COMPUTED | chembl.activities ws-2.x
- Most potent retrieved compound: CHEMBL29197 [E-0019] — RETRIEVED | CHEMBL29197 @ 2026-11-11

<sub>claims: E-0010, E-0012, E-0016, E-0017, E-0018, E-0019, E-0025</sub>

## Independent cross-check

> - critic claims recomputed: 0 [E-0026] — COMPUTED | aletheia.critic 1.0
> - critic recomputation mismatches: 0 [E-0027] — COMPUTED | aletheia.critic 1.0
> - predicted claims total: 0 [E-0028] — COMPUTED | aletheia.critic 1.0
> - predicted claims out of domain: 0 [E-0029] — COMPUTED | aletheia.critic 1.0
> - ledger claims total: 29 [E-0030] — COMPUTED | aletheia.critic 1.0
> - fewer than two oracles scored the candidates; no consensus check possible

<sub>claims: E-0026, E-0027, E-0028, E-0029, E-0030</sub>

## Interpretation (LLM reasoning)

> The retrieved identity and structural data consistently resolve to a single, well-characterized kinase target, with a high-resolution co-crystal structure confirming close agreement to the reference sequence, supporting confidence in the structural model used for downstream analysis. The bioactivity data show a wide spread between typical and best-case potency among known actives, with the most potent compound and a reasonably diverse set of scaffolds represented among top-ranked hits, suggesting multiple chemotypes are capable of engaging this target. This supports the target as a tractable and well-studied one for inhibitor discovery with structural and ligand data both available, but it does not establish efficacy, selectivity, or any clinical or in vivo relevance for the identified compounds. The physicochemical properties computed are descriptive of the protein itself and do not speak to druggability of any specific ligand or binding site.
> 
> *This paragraph is LLM reasoning over the findings above. It is tagged HYPOTHESIS: it contains no numbers of its own and was itself checked against the claims ledger before publication.*

## Safety

- verdict **ALLOW** (ordinary_research): Request is a standard target-information and medicinal chemistry query about EGFR kinase, a well-studied oncology drug target, with no weaponization or harm intent.

## Verification

- claims ledger: ledger coverage 100.0% (19/19 numeric tokens), 18/32 claims cited, 0 violation(s)

## Claims appendix

| claim | tag | key | value | units | provenance |
|---|---|---|---|---|---|
| E-0001 | [RETRIEVED] | gene_to_accession | P00533 |  | P00533 |
| E-0002 | [RETRIEVED] | uniprot_protein_name | Epidermal growth factor receptor |  | P00533 |
| E-0003 | [RETRIEVED] | sequence_length | 1210 | residues | P00533 |
| E-0004 | [RETRIEVED] | n_pdb_structures | 388 |  | P00533 |
| E-0005 | [COMPUTED] | sequence_gravy | -0.316 |  | uniprot.sequence_features rest-2026 |
| E-0006 | [COMPUTED] | net_charge_ph7 | -12 |  | uniprot.sequence_features rest-2026 |
| E-0007 | [RETRIEVED] | pdb_resolution | 1.07 | A | 8A27 |
| E-0008 | [COMPUTED] | structure_sequence_identity | 0.991 |  | pdb.chain_sequences rcsb-rest-v1 |
| E-0009 | [COMPUTED] | cocrystal_ligand | KY9 |  | pdb.ligands rcsb-rest-v1 |
| E-0010 | [RETRIEVED] | chembl_release | ChEMBL_37 |  | ChEMBL ChEMBL_37 |
| E-0011 | [RETRIEVED] | gene_to_accession | P00533 |  | P00533 |
| E-0012 | [RETRIEVED] | chembl_target_id | CHEMBL203 |  | CHEMBL203 |
| E-0013 | [RETRIEVED] | uniprot_protein_name | Epidermal growth factor receptor |  | P00533 |
| E-0014 | [RETRIEVED] | sequence_length | 1210 | residues | P00533 |
| E-0015 | [RETRIEVED] | n_pdb_structures | 388 |  | P00533 |
| E-0016 | [RETRIEVED] | n_unique_actives | 271 |  | CHEMBL203 |
| E-0017 | [COMPUTED] | pchembl_median | 6.72 |  | chembl.activities ws-2.x |
| E-0018 | [COMPUTED] | pchembl_max | 10.6 |  | chembl.activities ws-2.x |
| E-0019 | [RETRIEVED] | most_potent_active | CHEMBL29197 |  | CHEMBL29197 |
| E-0020 | [COMPUTED] | sequence_gravy | -0.316 |  | uniprot.sequence_features rest-2026 |
| E-0021 | [COMPUTED] | net_charge_ph7 | -12 |  | uniprot.sequence_features rest-2026 |
| E-0022 | [RETRIEVED] | pdb_resolution | 1.07 | A | 8A27 |
| E-0023 | [COMPUTED] | structure_sequence_identity | 0.991 |  | pdb.chain_sequences rcsb-rest-v1 |
| E-0024 | [COMPUTED] | cocrystal_ligand | KY9 |  | pdb.ligands rcsb-rest-v1 |
| E-0025 | [COMPUTED] | n_distinct_scaffolds_top60 | 18 |  | rdkit.scaffold 2026.09.2 |
| E-0026 | [COMPUTED] | critic_claims_recomputed | 0 |  | aletheia.critic 1.0 |
| E-0027 | [COMPUTED] | critic_recomputation_mismatches | 0 |  | aletheia.critic 1.0 |
| E-0028 | [COMPUTED] | predicted_claims_total | 0 |  | aletheia.critic 1.0 |
| E-0029 | [COMPUTED] | predicted_claims_out_of_domain | 0 |  | aletheia.critic 1.0 |
| E-0030 | [COMPUTED] | ledger_claims_total | 29 |  | aletheia.critic 1.0 |
| E-0031 | [COMPUTED] | identity_checks_passed | 2 |  | aletheia.identity_check 1.0 |
| E-0032 | [COMPUTED] | identity_checks_total | 2 |  | aletheia.identity_check 1.0 |
