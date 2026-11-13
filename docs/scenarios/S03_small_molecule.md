# S03 — Property and ADMET profile of named drugs

*track: small_molecule · generated from run `run-20261113T013350-d367b3` on 2026-11-12T22:33:50 · pattern `supervisor` · LLM backend `replay/rules (offline)`*

## User request

> Profile erlotinib and imatinib: physicochemical descriptors, drug-likeness, structural alerts and ADMET proxies.

## Expected answer (declared before the run)

Resolves both names through PubChem, computes RDKit descriptors, QED and SA score, screens PAINS/Brenk/NIH alerts, and reports ADMET proxies flagged as literature equations with unverified constants.

## What the system planned

- intents: `property_profile`
- planner: `callable+cache`
- agents invoked: `property_agent`, `critic`
- tools called (20): `pubchem.compound_by_name`, `rdkit.standardize`, `rdkit.descriptors`, `rdkit.druglikeness`, `rdkit.alerts`, `admet.profile`

## Actual result

### What the system did

Planner `callable+cache` routed this request to the intents property_profile.

- `S1` **property_agent** -> profile_molecules — descriptors and alerts for the molecules named by the user
- `S2` **critic** -> cross_check — independent recomputation and applicability-domain audit

Tools actually invoked: `admet.profile`, `pubchem.compound_by_name`, `rdkit.alerts`, `rdkit.descriptors`, `rdkit.druglikeness`, `rdkit.standardize`.

### Property profile — user:erlotinib

`C#Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1`

- MW: 393.443 Da [E-0003] — COMPUTED | rdkit.descriptors 2026.09.2
- cLogP: 3.405  [E-0004] — COMPUTED | rdkit.descriptors 2026.09.2
- TPSA: 74.73 A^2 [E-0005] — COMPUTED | rdkit.descriptors 2026.09.2
- rotatable bonds: 10  [E-0008] — COMPUTED | rdkit.descriptors 2026.09.2
- H-bond donors: 1  [E-0006] — COMPUTED | rdkit.descriptors 2026.09.2
- H-bond acceptors: 7  [E-0007] — COMPUTED | rdkit.descriptors 2026.09.2
- heavy atoms: 29  [E-0011] — COMPUTED | rdkit.descriptors 2026.09.2
- QED: 0.418  [E-0016] — COMPUTED | rdkit.descriptors 2026.09.2
- SA score: 2.478  [E-0017] — COMPUTED | rdkit.descriptors 2026.09.2
- Ro5 violations: 0  [E-0018] — COMPUTED | rdkit.druglikeness 2026.09.2
- structural alerts: 2  [E-0019] — COMPUTED | rdkit.alerts 2026.09.2
- ESOL logS: -4.173 log10(mol/L) [E-0020] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- CNS-MPO-like: 5.188  [E-0021] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- structural alerts: BRENK:Aliphatic_long_chain; BRENK:triple_bond

### Property profile — user:imatinib

`Cc1ccc(NC(=O)c2ccc(CN3CCN(C)CC3)cc2)cc1Nc1nccc(-c2cccnc2)n1`

- MW: 493.615 Da [E-0025] — COMPUTED | rdkit.descriptors 2026.09.2
- cLogP: 4.59  [E-0026] — COMPUTED | rdkit.descriptors 2026.09.2
- TPSA: 86.28 A^2 [E-0027] — COMPUTED | rdkit.descriptors 2026.09.2
- rotatable bonds: 7  [E-0030] — COMPUTED | rdkit.descriptors 2026.09.2
- H-bond donors: 2  [E-0028] — COMPUTED | rdkit.descriptors 2026.09.2
- H-bond acceptors: 7  [E-0029] — COMPUTED | rdkit.descriptors 2026.09.2
- heavy atoms: 37  [E-0033] — COMPUTED | rdkit.descriptors 2026.09.2
- QED: 0.389  [E-0038] — COMPUTED | rdkit.descriptors 2026.09.2
- SA score: 2.332  [E-0039] — COMPUTED | rdkit.descriptors 2026.09.2
- Ro5 violations: 0  [E-0040] — COMPUTED | rdkit.druglikeness 2026.09.2
- structural alerts: 0  [E-0041] — COMPUTED | rdkit.alerts 2026.09.2
- ESOL logS: -5.81 log10(mol/L) [E-0042] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- CNS-MPO-like: 2.956  [E-0043] — PREDICTED | admet.profile rule-based-1.0 | AD=NOT_ASSESSED
- structural alerts: liability:hERG-type basic amine with cLogP>3

### Independent cross-check

- critic claims recomputed: 8 [E-0045] — COMPUTED | aletheia.critic 1.0
- critic recomputation mismatches: 0 [E-0046] — COMPUTED | aletheia.critic 1.0
- predicted claims total: 4 [E-0047] — COMPUTED | aletheia.critic 1.0
- predicted claims out of domain: 0 [E-0048] — COMPUTED | aletheia.critic 1.0
- ledger claims total: 48 [E-0049] — COMPUTED | aletheia.critic 1.0
- 4 predicted value(s) have no applicability-domain verdict and are reported as such
- fewer than two oracles scored the candidates; no consensus check possible

### Interpretation (LLM reasoning)

Across both compounds, the computed descriptor profiles fall within ranges generally regarded as drug-like, with no Lipinski violations and ring, polarity, and lipophilicity values consistent with orally dosed small molecules. The drug-likeness scoring and synthetic accessibility estimates suggest reasonably favorable and synthetically tractable profiles, though the presence of structural alerts for one of the compounds warrants follow-up on potential reactive or promiscuous substructures rather than dismissal. The solubility and CNS-relevant composite predictions are in-silico proxies only, and the panel-pass tally reflects computational heuristics rather than experimental developability data. None of these results establish efficacy, safety, or clinical relevance for either compound; they support only a preliminary physicochemical and rule-based triage, and should be followed by orthogonal computational checks and experimental validation before any further inference is drawn.

*This paragraph is LLM reasoning over the findings above. It is tagged HYPOTHESIS: it contains no numbers of its own and was itself checked against the claims ledger before publication.*

## Verification

- claims ledger: ledger coverage 100.0% (42/42 numeric tokens), 31/49 claims cited, 0 violation(s)
- answer blocked by verifier: **False**
- safety verdict: **ALLOW**

## Invariant checks

- result: **PASS**

## Trace

- run log: `runs/run-20261113T013350-d367b3.jsonl`
- structured answer: `runs/run-20261113T013350-d367b3.answer.json`
- wall time: 0.77 s, LLM calls: 3, tool calls: 20 (12 served from cache)
