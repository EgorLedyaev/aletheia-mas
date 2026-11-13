# Reproducibility manifest

Generated 2026-11-13T04:30:07+00:00 by `python scripts/make_manifest.py`. Machine-readable copy: `registry/manifest.json`.

## Environment

- Aletheia 0.9.0
- Python 3.11.18 on Windows-10-10.0.26200-SP0

| package | version |
|---|---|
| rdkit | 2026.09.2 |
| numpy | 2.4.6 |
| scipy | 1.17.1 |
| pandas | 3.1.1 |
| sklearn | 1.9.1 |
| pydantic | 2.14.3 |
| matplotlib | 3.11.2 |
| selfies | 2.1.1 |
| fastapi | 0.162.4 |
| yaml | 6.0.3 |

## Fixed seeds and parameters

- `run.seed` = 20261111 (generators, scaffold split, critic sampling)
- `docking.seed` = 42
- docking: exhaustiveness 8 for screening, 24 for redocking validation, num_modes 9, box padding 5.0 Å
- QSAR: scaffold split, test fraction 0.2, conformal alpha 0.1, RandomForestRegressor(n_estimators=300, min_samples_leaf=2)

## Data snapshots

Database content is versioned by the retrieval date recorded on every RETRIEVED claim, and by the ChEMBL release string captured per run. Cached tool results live in `cache/tools/<tool>/<version>_<hash>.json` where the hash covers the tool name, its version, **a hash of the tool's own source code**, and its parameters — so changing an implementation invalidates exactly its own cached results.

| result file | sha256 (16) | produced |
|---|---|---|
| `eval/docking_validation.json` | `61054025feb68a8d` | 2026-11-11T22:25:03+00:00 |
| `eval/final_suite.json` | `59fb03d330fcdef3` | 2026-11-12T22:34:05+00:00 |
| `eval/harness_report.json` | `2b94226e85fe86f5` | 2026-11-12T21:59:09+00:00 |
| `eval/redteam_results.json` | `31fa48fdffd73fc0` | 2026-11-12T21:49:02+00:00 |

## Binary provenance

| artefact | sha256 (16) |
|---|---|
| `tools/vina/vina_1.2.7_win.exe` | `e0c4b2715e0c1a74` |
| `models/hit_calibrator_CHEMBL203.pkl` | `74fcabdb8a796b3b` |
| `models/qsar_CHEMBL203.pkl` | `59e82d69f106f1be` |

- tool/licence registry `registry/tools.yaml`: `ed1ac59e8b7540c5`
- 88 source files hashed; full list in `registry/manifest.json`

## Reproducing a published number

1. `make setup` (or `.\scripts\setup.ps1`) — installs the package, fetches the official Vina binary and re-verifies the tool registry.
2. `python -m aletheia.cli scenarios --run` — re-runs all 12 scenarios and regenerates every scenario card from the fresh run logs.
3. Open the card, take the claim id of the number in question, and look it up in the claims appendix of `runs/<run_id>.answer.md`: it carries the tool, its version, the parameter hash and the call id.
4. `python -m eval.harness` reproduces the orchestration comparison, the ablations and the baselines; `python eval/redteam.py` reproduces the red-team pass.

## v2 hardening sprint: what regenerates what

Every generated artefact is produced by one entry point:

```
python scripts/regenerate_all.py          # funnel, figures, deck, manifest, in dependency order
python scripts/regenerate_all.py --list   # the order itself
```

| script | reads | writes |
|---|---|---|
| `scripts/funnel_report.py` | `runs/*.jsonl` claims ledgers | `eval/funnel_table.json`, `docs/funnel_table.md` |
| `scripts/make_figure_data.py` | the S07 run ledger | `eval/figure_data_s07.json` |
| `scripts/make_generator_figure.py` | that file | `figures/generator_comparison.png` |
| `scripts/bench_docking.py` | ChEMBL cache / `eval/pubchem_thrombin.json` | `eval/docking_benchmark_*.json` |
| `scripts/docking_report.py` | those | `eval/docking_benchmark.json`, `docs/docking_validation_table.md`, `figures/docking_benchmark.png` |
| `scripts/calibrate_hit.py` | `models/qsar_CHEMBL203.pkl` + cached activities | `eval/calibration.json`, `models/hit_calibrator_CHEMBL203.pkl` |
| `scripts/make_calibration_figure.py` | those | `figures/calibration.png` |
| `scripts/bench_baselines.py` | live tools + the LLM backend | `eval/baseline_study.json` |
| `scripts/make_baseline_figure.py` | that file | `figures/baseline_study.png` |
| `scripts/make_dashboard.py` | `eval/harness_report.json`, `eval/funnel_table.json` | `figures/eval_dashboard.png` |
| `scripts/make_deck.py` | `docs/deck.md` | `docs/deck.pdf`, `figures/deck/slide_*.png` |

Seeds: 42 for docking and generator sampling, 20261111 for the activity model and every bootstrap,
2000 resamples per interval. The docking benchmark is resumable: per-ligand results are cached in
`eval/docking_bench_cache.json` keyed by receptor, scoring function and ligand hash.

Runtimes measured on this host (Windows, 16 cores, no GPU): EGFR benchmark (2 receptors x 70
ligands x 2 scoring functions) 4 422 s at 14 workers; thrombin 4 919 s at 12; baseline study
(24 queries x 4 systems) 380-2 426 s depending on LLM cache warmth; 13-scenario suite 375 s after
a docking-cache invalidation, ~15 s warm.

GPU route: a Colab T4 is reachable only in host-run mode -- the operator pastes one command and the CLI uploads a single self-contained script (the dataset is embedded, because `colab run` uploads only the script). Measured by the smoke job recorded in `eval/gpu_smoke.json`: Tesla T4, 14913 MiB reported by torch (15360 MiB by nvidia-smi), torch 2.14.1+cu130, CUDA 13.0, Python 3.13.16, transformers 5.22.1, RDKit absent from the image (installed per job). `colab.EXE` cannot be driven from the build sandbox (it aborts inside its own auto-update check), so no demo-critical result depends on it.
