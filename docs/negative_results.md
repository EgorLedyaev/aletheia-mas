# Negative results and defects found

Kept deliberately, because a system whose selling point is "no fabricated results" has to show the
results that did not flatter it. Everything below is reproducible from the repository.

## N1 — Vina does not enrich actives over decoys on EGFR/1M17

`scripts/validate_docking.py --pdb 1M17 --accession P00533 --n 10`
→ `eval/docking_validation.json`, figure `figures/docking_validation.png`

| quantity | value |
|---|---|
| known actives docked (pChEMBL ≥ 7) | 10 |
| property-matched presumed-inactive decoys | 10 |
| ROC AUC of the Vina ranking | **0.42** |
| enrichment factor at 10% | 1.0 |
| mean score, actives | −8.159 kcal/mol |
| mean score, decoys | −7.934 kcal/mol |
| mean gap | **0.225 kcal/mol** |

On this receptor, with this box and this preparation, the Vina score does **not** separate known
actives from property-matched molecules with no measured activity. The gap is far inside the
scoring function's own error.

*Consequence in the system*: `DockingAgent._receptor_enrichment` loads this measurement and
attaches it to every `vina_score` claim for that receptor, and emits an explicit degradation
stating that the scores must not be read as a potency ranking. The docking agent keeps running —
a pose is still a pose, and the contacts are still geometry — but the ranking claim is withdrawn.

*Caveat on the caveat*: the decoys are **presumed** inactive (absence of a ChEMBL measurement),
not measured inactives, and n = 10 + 10 is small. This is a setup sanity check, not a benchmark.

**Superseded, 2026-11-12.** That ROC AUC of 0.42 came from 10 known actives against 10 *presumed*
inactives (molecules with no ChEMBL measurement against the target). The systematic validation now
uses **measured inactives** on three receptors: on 1M17 Vina gives
**0.632** with 95% CI [0.4794, 0.7695] — still not usable for
ranking under the pre-registered rule, but the honest number is this one, not 0.42. The finding
that the receptor fails to enrich stands; its magnitude was wrong because the decoy set was weak.
See `docs/docking_validation_table.md` and N10.

## N2 — Redocking: the near-native pose is sampled but mis-ranked

Re-docking the co-crystal ligand AQ4 (erlotinib) into its own receptor, exhaustiveness 24:

| quantity | value |
|---|---|
| top-1 pose RMSD | **4.188 Å** (fails the 2 Å convention) |
| best pose RMSD among the 9 modes | **1.361 Å** at rank 3 |
| score difference, rank 1 vs rank 3 | 0.149 kcal/mol |

Diagnosis emitted by the system: *"near-native pose was sampled but not ranked first: a
scoring-function failure, not a search failure"*.

This matters for honesty in two ways. First, an earlier single-run measurement of the same system
produced 1.213 Å and looked like a clean pass — that number came from one particular input
conformer, and quoting it alone would have overstated the setup. `docking.pose_rmsd_all_models`
now reports both numbers, always. Second, it is consistent with N1: a scoring function that
mis-ranks a 1.4 Å pose against a 4.2 Å pose by 0.15 kcal/mol is not a scoring function that can
rank distinct ligands by potency.

## N3 — Defects the claims verifier caught in our own reporter

The verifier blocked four scenarios on their first full run. All four were our bugs, not model
fabrications:

| # | symptom | cause | fix |
|---|---|---|---|
| D1 | `-11`, `16`, `27` untraceable | ISO timestamps in provenance badges tokenised into numbers | scrub ISO-8601 before scanning; badges print the date only |
| D2 | `1.2` untraceable in docking blocks | the tool *version* string `vina-1.2.7` read as a claim | version/accession/hash digits added to the resolvable metadata pool |
| D3 | `3` untraceable in binding-site blocks | the unit label `A^3` tokenised into `3` | `^` excluded from the number-token lookbehind |
| D4 | `0.339` untraceable although it was a claim | float half-ulp: `f"{0.3385:.3f}"` prints `0.339` while the tolerance test rejected it by 5e-19 | match on the printed representation at the token's precision |

## N4 — The two orchestration patterns looked different because of a label

The blackboard pattern initially failed 9 of 11 scenarios on ledger coverage while the supervisor
passed all 11. The cause was neither pattern: blackboard step ids are formatted `B-4`, which
tokenises to a bare `4`, while supervisor ids `S4` do not tokenise at all. After exempting step-id
digits explicitly, both patterns reach 100% coverage. Recorded because it is a clean example of a
measurement artefact that would otherwise have become a "finding" in the evaluation report.

## N5 — A stale cache served pre-fix numbers

After fixing the PDBQT atom-type mapping, `docking.pose_rmsd` kept returning the old value
(1.652 Å, 9 of 29 atoms matched) because the cache key contained only the tool name, version and
parameters — not the implementation. Fixed by hashing each tool's own source into the cache key
(`registry._code_hash`), so changing a tool invalidates exactly its own cached results and the
implementation identity travels in the recorded `params_hash`.

## N6 — The funnel is harsh, and that is reported

Canonical counts: `docs/funnel_table.md` (generated). In the recorded run of **S07**,
86 <!--funnel:S07.after_hazard_gate--> unique generated structures entered
the cheap-filter gate and **5** <!--funnel:S07.gate1_passed--> survived
(QED >= 0.30, <= 1 Ro5 violation, <= 1 structural alert, SA <= 6). In **S08**, seeded from a
different molecule and with all four generators available,
126 <!--funnel:S08.after_hazard_gate--> entered and
**104** <!--funnel:S08.gate1_passed--> survived at identical thresholds.

Novelty relative to the retrieved actives is low for three of four generators. In the recorded run that exercised all four (`run-20261113T013401-4077d6`), only SELFIES mutation routinely leaves the reference chemotypes (`frac_novel` = 0.625); BRICS recombination does so rarely (0.075), and reaction-SMARTS decoration and the LLM edits produced none at all (0.000 and 0.000) — while the novel structures are the least drug-like. No generator is presented as a solution.

## N7 — Two documents disagreed about the funnel, and neither was reproducible

A reviewer found the funnel quoted as 126 -> 5 in one place and 126 -> 104 in another. Both looked
defensible and neither was reproducible as stated.

Root cause, recovered from the run logs: the two figures came from **different scenarios** (S07 is
seeded with the erlotinib SMILES in the user's query, S08 with the most potent retrieved active),
and the smaller one came from a **side file captured mid-development**
(`eval/figure_data_s07.json`) that no run of the day reproduced. The same stale file also carried
G2's novelty as 0.00 when the run gave 0.075.

**Fix, not just a correction.** The funnel is generated once from each run's claims ledger
(`scripts/funnel_report.py` -> `docs/funnel_table.md`); figure inputs are rebuilt from the ledger
(`scripts/make_figure_data.py`); every funnel number in prose carries a
`<!--funnel:SCENARIO.stage-->` marker and is rewritten from the table by
`scripts/sync_funnel_docs.py`; and `tests/test_funnel.py` fails the build if a stored table, a
figure input or any marked number disagrees with the run log.

That machinery immediately proved its worth. A later run of S07 — made while the ChEMBL API was
down, so BRICS recombination could not contribute and three generators produced
86 <!--funnel:S07.raw_proposals--> candidates instead of 126 — legitimately
yields 5 <!--funnel:S07.gate1_passed--> survivors. The documents followed the
table automatically, and the test confirmed they had. A number that looks like the old mistake can
now be told apart from it, because the run it came from is recorded.

## N8 — The portfolio hit probability could not be calibrated, so it is no longer published

**Pre-registered criterion** (docs/preregistration.md W2): a hit is a molecule with measured
pChEMBL >= 7.0; the calibrator is fitted on the scaffold-split calibration fold only; the
probability stays a headline number only if its test-fold ECE is <= 0.10.

**Result: the criterion fails.** On the 54-molecule held-out fold:

| map | ECE (10 equal-count bins) | Brier | mean predicted P(hit) |
|---|---|---|---|
| hand-written linear map (what the system used) | 0.5584 | 0.4187 | 0.2934 |
| Platt, fitted on the calibration fold | 0.1977 | 0.1233 | 0.6542 |
| calibration-fold base rate | 0.5297 | 0.3346 | 0.3953 |

Observed hit rate on that fold: 0.8519.

**Why it fails is more interesting than that it fails.** A Bemis-Murcko scaffold split makes the
calibration and test folds non-exchangeable: the hit rate is 0.3953 on
the calibration fold and 0.8519 on the test fold. A calibrator fitted on one
cannot be valid on the other, and no choice of calibrator family repairs that — Platt was selected
over isotonic by cross-validated log-loss inside the calibration fold
(0.3659 vs
0.7815) and still lands at 0.1977.

**Consequence in the product.** `P(>=1 hit)` is no longer printed in any answer. The ranker still
registers it in the ledger as a diagnostic, with a bootstrap interval from refitting the
calibrator, and the reporter replaces it with an explicit withholding line naming the failed
criterion. The retracted headline number was **0.9651**; with a
calibrated map the same arithmetic gives **1.0**
[0.9999, 1.0] under independence and
**0.8527** [0.7131, 0.9313] if the
candidates are treated as one shared chance — which is the point: the number was always an
artefact of the correlation assumption rather than a measurement. Any probability the ledger does
hold is accompanied by the measured oracle disagreement (Spearman rho = 0.071 between the activity
model and docking), and candidates outside the model's applicability domain receive no probability
at all.

Figure: `figures/calibration.png`. Data: `eval/calibration.json`.

## N9 — Our own baseline study found five defects in us, and a single agent is still more accurate

The W4 study (24 graded queries, ground truth recomputed by RDKit/UniProt/RCSB/PubChem at run
time) was built to show that the baselines cannot support their numbers. It did show that — and it
also showed that **Aletheia was the least accurate system on the suite**: correctness 0.750
against 0.917 for a plain LLM, 0.958 for a single tool-using agent and **1.000** for the same
single agent wired to our own claims ledger (`eval/baseline_study_discovery.json`).

Five of the six failures were real defects, not grading artefacts:

1. structure selection ignored a ligand named in the request and returned its default
   highest-resolution pick (8A27) when asked which entry has **erlotinib** bound (1M17/AQ4);
2. the co-crystal ligand component id was computed and in the ledger but never published;
3. the rotatable-bond count was computed but absent from the published property table;
4. a target brief omitted the ChEMBL target id, because only the chemistry retriever resolved it;
5. a request for three analogue SMILES returned none, because generation was wired to depend on
   the chemistry retriever and ChEMBL was down — the generators that work from the user's seed
   alone were never reached.

The sixth was our grader's fault: it forbade every numeral in a "do not invent a value" answer, so
run metadata ("19.7s") and an unrelated retrieved sequence length counted as a fabricated IC50.

All five defects are fixed (RCSB chemical-structure search for the ligand constraint, three
publishing gaps closed, generation decoupled from retrieval) and the suite was re-run:
**0.9583** for Aletheia. The single agent with our ledger still scores
1.0, and we report that rather than hide it: on short
factual questions a planner, a critic and a reporter add latency and failure modes, not accuracy.
What they add is on the other axes — see the table in `docs/evaluation_report.md` section 9.

While fixing this we also found **two defects in the measurement itself**: identifier existence was
never checked on Aletheia's own answers (asymmetric), and a ChEMBL outage was being scored as
"nonexistent identifier", reporting a 40% fabrication rate for identifiers that all exist. That is
the same bug class as N4, found twice; the checker now separates *unverifiable* from *nonexistent*.

## N10 — On a non-kinase receptor the docking ordering is inverted

Validation across three receptors with measured inactives (`docs/docking_validation_table.md`)
found that on thrombin (1OYT, serine protease, ligands from PubChem BioAssay) Vina's ROC AUC is
**0.2904**, 95% CI [0.1467, 0.4459] — an interval lying entirely
**below** chance — and the measured inactives score **+0.670 kcal/mol
better** than the actives. Vinardo behaves the same (0.3156,
[0.1748, 0.4696]). This is the classic size and lipophilicity bias of an empirical
scoring function: thrombin's potent ligands are small, charged benzamidines, while its measured
inactives are larger and greasier, and both functions reward buried hydrophobic surface.

Consequence: a better docking score on that receptor is evidence of nothing, and the system now
says so — the docking agent emits a degradation naming the inversion and the ranker drops
`vina_score` from its objectives whenever the receptor/oracle pair fails its pre-registered
criterion.

## N11 — A shared output filename silently mislabelled a docking result

Adding a second scoring function exposed a defect in our own caching. `docking.vina_dock` wrote
its poses to a path derived from the ligand only — `redock_AQ4_out.pdbqt` — while the tool cache
keyed correctly on the scoring function. So when the Vinardo call was served from cache (no
re-run, no file write) and a later Vina call had overwritten that file, the RMSD step read the
**Vina** poses and the claim was published as a Vinardo redocking: 4.188 A, carrying a
`scoring_function: vinardo` tag that was not true of the geometry it described.

Found by an independent review of our own run logs, not by a test. Two things made it findable:
the number was byte-identical to a Vina result recorded a day earlier, and re-docking the agent's
own receptor, box and ligand with the binary directly gave 2.685 A for Vinardo against 4.188 A for
Vina — same inputs, different function, different answer.

Fixed by putting the scoring function in every docking output path, and by recording the scoring
function inside the claim's `validation` block so a mislabelled pose cannot look right again. The
corrected values: **Vinardo on 1M17 redocks to 2.685 A top-1** (best of modes 1.23 A at rank 8),
**Vina to 4.188 A** (best 1.361 A at rank 3) — so the oracle that passes the enrichment criterion
on this receptor is also the one that reproduces the crystal pose more closely, which is the
result we would have claimed for the wrong reason had nobody checked.

A cache that keys on parameters but writes to a path that does not is a provenance bug, in the
system whose whole purpose is provenance. It is logged here for that reason.


## N12 — The activity model generalises to another kinase but not to a protease

The cross-target benchmark (`scripts/make_cross_target_figure.py`, `docs/cross_target_summary.md`)
refits the pipeline's own activity model with the identical protocol -- scaffold split, 300-tree
forest, split-conformal at alpha 0.1, seed 20261111 -- on three ligand sets and compares each
model against baselines computed on its own split.

On CDK2, a kinase the pipeline had never seen, the model behaves as it does on EGFR: test RMSE
0.855 against 1.337 for a 1-NN Tanimoto lookup and
0.979 for the train mean, with conformal coverage
0.943 against a nominal 0.90.

On thrombin it does not. Test RMSE is 1.093 against
1.072 for the same 1-NN baseline -- **the model does not beat nearest-
neighbour lookup** -- and the conformal interval covers 0.859
of the held-out scaffolds, below its nominal 0.90. The thrombin set is a two-mode selection from
PubChem dose-response assays (actives at pAct >= 7, measured inactives at pAct <= 5, nothing
between), so a scaffold split moves whole modes between train and test and the exchangeability
that conformal prediction assumes does not hold -- the same mechanism that broke the hit-probability
calibration in N8.

This is the second time the same assumption has failed in this work, and it is the reason the
system reports the applicability domain and the coverage next to every predicted number instead of
reporting the number alone. On thrombin the docking oracle fails its criterion as well (both
scoring functions below chance, N10), so for that target the ranker is left with properties and an
activity model that is no better than a lookup -- and the honest output is a shorter answer, not a
confident one.
