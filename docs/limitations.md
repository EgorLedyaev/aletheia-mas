# Limitations and future work

Stated plainly, because the case requires transparent separation of computation, prediction and
hypothesis — and because a jury will find these anyway.

## What the system genuinely does

* Real computation: RDKit descriptors, QED, SA score, PAINS/Brenk/NIH alerts, Murcko scaffolds,
  Butina clustering, exact Pareto sorting, AutoDock Vina 1.2.7 docking with pose RMSD and
  geometric contact analysis, a LIGSITE-style cavity grid, random-forest QSAR with a scaffold
  split and split-conformal intervals.
* Real retrieval with accession + date: UniProtKB, RCSB PDB, AlphaFold DB, ChEMBL, PubChem.
* Real enforcement: 12/12 scenarios published at 100% ledger coverage; 7/7 red-team probes held.

## What it does not do

1. **No trained ADMET model.** `aletheia/tools/admet.py` is rule panels (Lipinski, Veber, Egan,
   Ghose, lead-likeness, Ro3) plus two literature equations — an ESOL-type solubility estimate and
   a CNS-MPO-style desirability sum — whose constants are flagged `[UNVERIFIED-COEFFICIENTS]`
   because the source papers could not be opened from this environment to check them. There is no
   hERG model, no CYP model, no clearance model. The hERG output is a two-condition structural
   triage flag, and says so.
2. **No pretrained deep generative model.** Generation is four samplers: reaction-SMARTS
   decoration, BRICS recombination of retrieved actives, SELFIES token mutation, and LLM-proposed
   edits validated by RDKit. No deep generator with a verified offline CPU build was available on
   this host, and the project refuses to claim one it did not run.
3. **No co-folding, no MD, no free-energy calculation.** Boltz/Chai-class co-folding and GPU
   docking were scoped as optional extras. A GPU is reachable only in host-run mode — the operator
   pastes one command and a Colab T4 runs a staged script (verified: Tesla T4, 14 913 MiB,
   torch 2.14.1+cu130, RDKit absent from the image and installed per job) — so no GPU result is
   on the demo path and nothing demo-critical depends on it. Not attempted, not claimed.
4. **Docking is rigid-receptor, single-conformer, no explicit waters, no protonation model.**
   Ligands get one ETKDG conformer minimised with MMFF94; the receptor is protonated by Open Babel
   at pH 7.4 with no tautomer search. Vina scores are reported as docking scores, never as
   affinities.
5. **Docking scores do not discriminate on most receptors we tested.** Across three receptors
   with measured inactives (35 per class selected; 28/33
   and 27/25 usable after failures), exactly one
   receptor/oracle pair clears chance: Vinardo on 1M17, ROC AUC 0.734
   95% CI [0.6006, 0.8517]. On thrombin the ordering is *inverted*
   (0.290, interval entirely below chance). The system attaches the
   per-receptor, per-scoring-function measurement to every score it prints and refuses to rank on
   a pair that failed (`docs/docking_validation_table.md`, negative results N1 and N10).
6. **The QSAR model is weak and labelled weak.** Spearman ρ = 0.339 on held-out scaffolds with
   ±1.47 pChEMBL conformal intervals. It beats both mandatory baselines and is useful only as an
   ordering heuristic inside its applicability domain.
7. **The portfolio hit probability is no longer published at all.** We tried to calibrate it
   against a pre-declared hit definition (measured pChEMBL >= 7.0) and it failed its
   pre-registered criterion: test-fold ECE 0.198 against a threshold of 0.10
   (`docs/negative_results.md` N8, `figures/calibration.png`). The cause is structural rather than
   a bad calibrator choice — a Bemis-Murcko scaffold split leaves the calibration and test folds
   with hit rates of 0.395 and 0.852, so no map fitted on one is valid on the other. The ranker
   still records the probability in the ledger as a diagnostic, with a bootstrap interval and the
   measured oracle disagreement beside it; the reporter prints an explicit withholding line in its
   place. Candidates outside the activity model's applicability domain receive no probability.
8. **The pocket detector is our own re-implementation**, not fpocket or P2Rank (no win-64 build
   was available). It is validated on one co-crystal case (0.44 Å localisation on 8A27) — one case
   is not a benchmark.
9. **The safety gate is a lexicon plus a classifier, not a regulatory screen.** It does not check
   CWC schedules or national controlled-substance lists against an authoritative source, and it
   cannot verify institutional authorisation. A determined paraphrase, particularly in a language
   the lexicon does not cover, may pass it.
10. **The verifier checks traceability, not correctness.** It guarantees that every published
    number came from a tool run with recorded parameters. It cannot tell you that the tool was the
    right tool, that the receptor was the right receptor, or that a model's prediction is true.
    Garbage in, *traceable* garbage out.
11. **Single-turn, single-user, no persistence across sessions.** There is no conversation memory,
    no project state, no multi-user access control, no authentication on the web UI (bind to
    localhost only).
12. **Scale.** Tested with up to a few hundred candidates and a few hundred ChEMBL records per
    target. The ledger holds ~2800 claims for a full campaign in memory; nothing has been profiled
    beyond that.

## Future work, in the order we would actually do it

1. Replace the ADMET proxies with a licence-verified toolkit, and attach the same
   baseline/applicability discipline to it as to the QSAR model.
2. Add a second structure-based oracle that the enrichment check shows *does* discriminate on the
   target at hand, and let the critic's oracle-agreement check gate the ranking.
3. Broaden the enrichment validation: more receptors, more decoys, measured inactives where
   ChEMBL has them, so the per-receptor verdict is statistically meaningful.
4. Injection probes through retrieved content (hostile strings inside database records).
5. An active-learning loop over generate → score → refine with a held-out oracle, to test whether
   the funnel improves candidates or only re-ranks them.
6. GPU tracks (co-folding, protein-LM embeddings, protein design) on a compute path that can be
   driven programmatically.
7. Multi-turn sessions with persistent project state and a human-in-the-loop checkpoint before any
   expensive batch.
