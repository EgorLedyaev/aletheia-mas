# Pre-registered acceptance criteria (v2 hardening sprint)

Written **before** the corresponding experiments were run, so that a result that fails its
criterion cannot be re-described afterwards as a success. Each entry states the comparison, the
statistic, the decision rule and what happens on failure. Failures are recorded in
`docs/negative_results.md`, not deleted.

Fixed before any run:

* a **hit** is a molecule whose measured pChEMBL against the stated target is **>= 7.0**;
* a **measured inactive** is a molecule with a ChEMBL activity record against that target whose
  pChEMBL is **<= 5.0** (absence of a record is not inactivity);
* all confidence intervals are **95% bootstrap percentile** intervals, 2000 resamples, resampling
  ligands (stratified by label) or calibration points as stated, seed 42;
* "beats" means the interval for the difference **excludes 0** in the stated direction.

## W2 — calibrated probability that a portfolio contains >= 1 hit

* Calibrator fitted on the **scaffold-split calibration fold only** (never on test): the same
  43-molecule fold the conformal quantile uses, with predictions made by the model fitted on the
  174-molecule fit fold, so every calibration point is out-of-sample for the regressor.
* Two candidate calibrators, **Platt scaling** (logistic on the predicted pChEMBL) and
  **isotonic regression**; the one with the lower **5-fold cross-validated log-loss inside the
  calibration fold** is selected. The current uncalibrated linear map is carried through as the
  baseline, so the comparison is against what the system does today.
* Test-fold ECE uses **10 equal-count bins** as the decision statistic; bin occupancy is reported
  alongside, since the test fold holds 54 molecules.
* Reported on the held-out **test fold**: ECE (10 equal-count bins), Brier score, reliability
  diagram.
* **Adopt** the calibrated probability as a headline number only if **ECE <= 0.10** on test.
  Otherwise it is demoted to a diagnostic, shown with its interval and an explicit warning.
* No probability is emitted for a candidate outside the model's applicability domain.
* Any portfolio probability is printed next to the measured oracle disagreement
  (Spearman rho between the activity model and docking).

## W3 — docking validation and a second structure-based oracle

* Validation per receptor on **>= 30 actives and >= 30 property-matched measured inactives**,
  on **>= 3 receptors** including 8A27 and at least one non-kinase.
* A receptor is **usable for ranking** only if its ROC AUC 95% CI lower bound is **> 0.5**.
  Receptors failing this are kept in the system but their scores are published with the
  degradation and may not drive ranking.
* **Non-kinase ligand source** (added 2026-11-12, before the thrombin run, because the ChEMBL web
  API was returning HTTP 500 on every endpoint): PubChem BioAssay records whose target is UniProt
  **P00734**. An **active** is a record with Activity Outcome `Active` and a potency value
  <= 0.1 uM (pAct >= 7); a **measured inactive** is a record with Activity Outcome `Inactive`, or
  a potency value >= 10 uM (pAct <= 5). Per compound the most potent record decides, so a compound
  with any potent measurement can never be drawn as a decoy. Decoys are property-matched to the
  actives on MW and cLogP, exactly as for the ChEMBL receptors, and the receptor's row in the
  benchmark table carries PubChem as its provenance.
* A second scoring function (Vinardo) is **adopted** only if the paired bootstrap interval for
  **AUC(Vinardo) - AUC(Vina)** excludes 0 in its favour on the same ligands and receptor.
  If it does not, it is reported as "no measured gain" and left out of the ranking path.

## W6a — trained ADMET models replacing the constant-coefficient proxies

* Scaffold split, >= 2 baselines (train-mean and 1-NN Tanimoto), conformal intervals, explicit
  applicability domain.
* **Adopt** only if test RMSE (or AUC for a classification endpoint) beats **both** baselines with
  a 95% bootstrap interval on the difference that excludes 0.

## W6b — deep generative model as a fifth generator

* Trained on ChEMBL SMILES, target-focused fine-tune; 20% of known actives held out from
  training and from the retrieval index.
* Report validity, uniqueness, novelty, and **recall of the held-out actives**.
* **Adopt as G5** only if it contributes candidates that are simultaneously novel
  (max Tanimoto < 0.4 to the retrieved actives) and drug-like (passes the same cheap-filter gate)
  that G1-G4 do not produce, at a rate whose bootstrap interval excludes 0.

## W6c — stronger activity model

* Same scaffold split, same test fold as the current random forest.
* **Adopt** only if test RMSE beats the current model with a 95% interval on the paired
  difference that excludes 0. A tie is reported as a tie.

## W6d — active learning with a held-out oracle

* The acquisition loop may query only the **search oracle**; the **held-out oracle** is never
  visible to it.
* Report the search-oracle gain and the held-out-oracle gain side by side; the **gap** is the
  Goodhart measurement and is published whatever it shows.
