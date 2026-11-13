"""Emit a reproducibility manifest: versions, seeds, file hashes, data snapshot dates.

    python scripts/make_manifest.py   ->  docs/reproducibility.md + registry/manifest.json
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

TRACKED_DIRS = ["aletheia", "eval", "scripts", "tests", "config"]
TRACKED_FILES = ["Makefile", "pyproject.toml", "README.md",
                 "tools/vina/vina_1.2.7_win.exe", "models"]


def _gpu_paragraph(here):
    """The GPU paragraph, built from eval/gpu_smoke.json -- never from memory."""
    import json as _json
    path = os.path.join(here, "eval", "gpu_smoke.json")
    if not os.path.exists(path):
        return ("GPU route: no smoke-test record in eval/gpu_smoke.json, so no GPU "
                "environment is claimed here.")
    with open(path, encoding="utf-8") as fh:
        g = _json.load(fh)
    rdkit = g.get("have_rdkit")
    return ("GPU route: a Colab T4 is reachable only in host-run mode -- the operator pastes "
            "one command and the CLI uploads a single self-contained script (the dataset is "
            "embedded, because `colab run` uploads only the script). Measured by the smoke "
            "job recorded in `eval/gpu_smoke.json`: {name}, {mib} MiB reported by torch "
            "({smi} MiB by nvidia-smi), torch {torch}, CUDA {cuda}, Python {py}, "
            "transformers {tf}, RDKit {rd}. `colab.EXE` cannot be driven from the build "
            "sandbox (it aborts inside its own auto-update check), so no demo-critical "
            "result depends on it.").format(
                name=g.get("gpu_name"), mib=g.get("gpu_total_MiB"),
                smi=g.get("nvidia_smi_total_MiB"), torch=g.get("torch"),
                cuda=g.get("cuda"), py=g.get("python"), tf=g.get("have_transformers"),
                rd=rdkit if rdkit else "absent from the image (installed per job)")


V2_SECTION = """
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

{gpu_paragraph}
"""


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    from aletheia import __version__
    from aletheia.core.config import load_config
    cfg = load_config()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    files = {}
    for d in TRACKED_DIRS:
        for root, _, names in os.walk(os.path.join(HERE, d)):
            if "__pycache__" in root:
                continue
            for n in names:
                if n.endswith((".py", ".yaml", ".yml")):
                    p = os.path.join(root, n)
                    files[os.path.relpath(p, HERE).replace("\\", "/")] = sha256(p)[:16]
    for f in TRACKED_FILES:
        p = os.path.join(HERE, f)
        if os.path.isfile(p):
            files[f] = sha256(p)[:16]
        elif os.path.isdir(p):
            for n in sorted(os.listdir(p)):
                q = os.path.join(p, n)
                if os.path.isfile(q):
                    files[f"{f}/{n}"] = sha256(q)[:16]

    pkgs = {}
    for mod in ["rdkit", "numpy", "scipy", "pandas", "sklearn", "pydantic", "matplotlib",
                "selfies", "fastapi", "yaml"]:
        try:
            m = __import__(mod)
            pkgs[mod] = str(getattr(m, "__version__", "unknown"))
        except ImportError:
            pkgs[mod] = "not installed"

    reg_path = os.path.join(HERE, "registry", "tools.yaml")
    registry_hash = sha256(reg_path)[:16] if os.path.exists(reg_path) else None
    snapshots = {}
    for name, f in [("docking_validation", "eval/docking_validation.json"),
                    ("final_suite", "eval/final_suite.json"),
                    ("harness_report", "eval/harness_report.json"),
                    ("redteam_results", "eval/redteam_results.json")]:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            snapshots[name] = {"file": f, "sha256_16": sha256(p)[:16],
                               "mtime": datetime.datetime.fromtimestamp(
                                   os.path.getmtime(p), datetime.timezone.utc
                               ).isoformat(timespec="seconds")}

    manifest = {
        "generated_at": now, "aletheia_version": __version__,
        "python": platform.python_version(), "platform": platform.platform(),
        "packages": pkgs,
        "seeds": {"run.seed": cfg["run"]["seed"], "docking.seed": cfg["docking"]["seed"],
                  "qsar.alpha": 0.1, "qsar.test_frac": 0.2},
        "docking_params": cfg["docking"],
        "verifier": cfg["verifier"],
        "llm": {"backends": cfg["llm"]["backends"], "replay_cache": cfg["llm"]["cache_dir"],
                "note": "every live LLM response is recorded to the replay cache, so an offline "
                        "run reproduces the recorded agent behaviour"},
        "registry_sha256_16": registry_hash,
        "result_snapshots": snapshots,
        "n_source_files": len(files), "source_hashes": files,
    }
    os.makedirs(os.path.join(HERE, "registry"), exist_ok=True)
    with open(os.path.join(HERE, "registry", "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)

    lines = ["# Reproducibility manifest", "",
             f"Generated {now} by `python scripts/make_manifest.py`. Machine-readable copy: "
             "`registry/manifest.json`.", "",
             "## Environment", "",
             f"- Aletheia {__version__}", f"- Python {manifest['python']} on {manifest['platform']}",
             "",
             "| package | version |", "|---|---|"]
    for k, v in pkgs.items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Fixed seeds and parameters", "",
              f"- `run.seed` = {cfg['run']['seed']} (generators, scaffold split, critic sampling)",
              f"- `docking.seed` = {cfg['docking']['seed']}",
              f"- docking: exhaustiveness {cfg['docking']['exhaustiveness']} for screening, "
              f"{cfg['docking'].get('redock_exhaustiveness')} for redocking validation, "
              f"num_modes {cfg['docking']['num_modes']}, box padding "
              f"{cfg['docking']['box_pad']} Å",
              "- QSAR: scaffold split, test fraction 0.2, conformal alpha 0.1, "
              "RandomForestRegressor(n_estimators=300, min_samples_leaf=2)", "",
              "## Data snapshots", "",
              "Database content is versioned by the retrieval date recorded on every RETRIEVED "
              "claim, and by the ChEMBL release string captured per run. Cached tool results live "
              "in `cache/tools/<tool>/<version>_<hash>.json` where the hash covers the tool name, "
              "its version, **a hash of the tool's own source code**, and its parameters — so "
              "changing an implementation invalidates exactly its own cached results.", ""]
    if snapshots:
        lines += ["| result file | sha256 (16) | produced |", "|---|---|---|"]
        for k, v in snapshots.items():
            lines.append(f"| `{v['file']}` | `{v['sha256_16']}` | {v['mtime']} |")
    lines += ["", "## Binary provenance", "",
              "| artefact | sha256 (16) |", "|---|---|"]
    for k, v in files.items():
        if k.startswith("tools/vina") or k.startswith("models/"):
            lines.append(f"| `{k}` | `{v}` |")
    lines += ["", f"- tool/licence registry `registry/tools.yaml`: `{registry_hash}`",
              f"- {len(files)} source files hashed; full list in `registry/manifest.json`", "",
              "## Reproducing a published number", "",
              "1. `make setup` (or `.\\scripts\\setup.ps1`) — installs the package, fetches the "
              "official Vina binary and re-verifies the tool registry.",
              "2. `python -m aletheia.cli scenarios --run` — re-runs all 12 scenarios and "
              "regenerates every scenario card from the fresh run logs.",
              "3. Open the card, take the claim id of the number in question, and look it up in the "
              "claims appendix of `runs/<run_id>.answer.md`: it carries the tool, its version, the "
              "parameter hash and the call id.",
              "4. `python -m eval.harness` reproduces the orchestration comparison, the ablations "
              "and the baselines; `python eval/redteam.py` reproduces the red-team pass.", ""]
    body = "\n".join(lines)
    body += V2_SECTION.format(gpu_paragraph=_gpu_paragraph(HERE))
    with open(os.path.join(HERE, "docs", "reproducibility.md"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(body)
    print(f"manifest: {len(files)} source files, {len(pkgs)} packages, "
          f"{len(snapshots)} result snapshots")
    return 0


if __name__ == "__main__":
    sys.exit(main())
