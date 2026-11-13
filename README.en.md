# Aletheia — a provenance-enforcing LLM multi-agent system for drug design

*Русская версия: [README.md](README.md).*

**ХИМБИО-ХАКАТОН «СИНТЕЗ» 2026 · Case 1 — Development of a multi-agent system for designing drug molecules**

Aletheia takes a natural-language request, routes it with an LLM, coordinates a team of
specialist agents over real scientific tools and databases, and returns a structured answer in
which **every number can be traced to the tool run that produced it**.

The differentiator is not the agent roster — tool-calling chemistry agents are established work
(ChemCrow, Coscientist; see `docs/sota_audit.md`). It is the **claims ledger with a blocking
verifier**: an answer containing a number that no tool produced is refused, mechanically, before
it ever reaches the user.

```
natural language ──▶ safety gate ──▶ LLM planner ──▶ specialist agents ──▶ critic ──▶ reporter
                         │                                   │                          │
                      refuse &                      real tools: RDKit, Vina,        claims ledger
                      log event                     UniProt, PDB, AlphaFold,      ── verifier ──▶ answer
                                                    ChEMBL, PubChem                  or refusal
```

## The four provenance tags

Every value carries one, and the renderer prints it:

| tag | meaning | contract enforced in code |
|---|---|---|
| `COMPUTED` | a deterministic tool produced it | requires tool, version and a parameter hash |
| `PREDICTED` | a statistical model produced it | requires an applicability-domain verdict and an uncertainty estimate (or an explicit statement that none is available) |
| `RETRIEVED` | a database record | requires an accession and a retrieval date |
| `HYPOTHESIS` | LLM reasoning | **may not carry a numeric value** — numbers must come from tools |

That last row is the one that matters: the LLM cannot emit an IC50, a docking score or a
molecular weight and have it survive validation.

## Quick start

```bash
# Linux / macOS / WSL
make setup        # pip install -e . ; fetch the official Vina binary ; verify the tool registry
make demo         # run the scenario suite and regenerate the scenario cards

# Windows PowerShell
.\scripts\setup.ps1
.\scripts\demo.ps1
```

Then ask it something:

```bash
python -m aletheia.cli ask "Dock erlotinib into EGFR structure 1M17 and validate it by redocking"
python -m aletheia.cli ask "Profile erlotinib and imatinib" --echo
python -m aletheia.cli ask "..." --pattern blackboard      # the alternative orchestration
python -m aletheia.cli ask "..." --offline                 # cache-only, no network, no API key
python -m aletheia.cli tools                               # the tool registry
python -m aletheia.cli scenarios --run                     # the whole suite
```

`ALETHEIA_OFFLINE=1` forces the fully offline path: cached tool results plus recorded LLM
responses. Every output states whether it is `live` or `cached` and names its run id.

## Web UI

```bash
python -m uvicorn aletheia.web.app:app --host 127.0.0.1 --port 8000
```

A chat box, a live agent trace with provenance badges, and a claims-ledger panel beside the
answer. Routes are covered by an in-process test (`tests/test_web.py`), so the UI can be verified
without opening a port.

## Requirements

* Python ≥ 3.10, and **Open Babel** on `PATH` (`conda install -c conda-forge openbabel`) for
  PDBQT preparation.
* AutoDock Vina 1.2.7 — `make setup` downloads the official release binary for your platform and
  prints its SHA-256.
* An LLM backend, any of: `ANTHROPIC_API_KEY`, an OpenAI-compatible server
  (`OPENAI_BASE_URL` + `OPENAI_API_KEY`), a local Ollama (`OLLAMA_HOST`), or **none at all** —
  without a backend the planner falls back to deterministic keyword routing and the system still
  runs, reporting `planner=rules`.

## Layout

```
aletheia/core/        contracts, provenance, claims ledger + verifier, LLM layer, tool registry
aletheia/tools/       58 registered tools (RDKit, ChEMBL, PubChem, UniProt, PDB, AlphaFold,
                      Vina docking, pocket detection, generators, ADMET proxies, QSAR, ranking)
aletheia/agents/      planner, safety, target analyst, structure analyst, retriever, generator,
                      property, QSAR, docking, ranker, critic, reporter
aletheia/orchestrator/ supervisor (hierarchical) and blackboard (parallel fan-out)
aletheia/eval/        scenario suite with deterministic invariants
eval/                 harness outputs, ablations, orchestration comparison
docs/                 architecture, SOTA audit, scenario cards, safety policy, compliance matrix
registry/             tool + licence registry with verification log
runs/                 one JSONL trace and one JSON/Markdown answer per run
```

## Generated figures and documents

Everything below is produced by a script and rebuilt in one command
(`python scripts/regenerate_all.py`); none of it is maintained by hand.

| Output | Script | What it shows |
|---|---|---|
| `figures/deck/provenance_architecture.png` | `make_provenance_figure.py` | the usual tool-calling pipeline against this one, with the measured numeric-coverage rates |
| `figures/deck/portfolio_molecules.png` | `make_portfolio_figure.py` | the eight selected molecules drawn against the erlotinib seed, modifications highlighted |
| `figures/deck/chemical_space.png` | `make_chemspace_figure.py` | ECFP4 projection of candidates against the measured actives, with Butina clusters and the objective-space Pareto front |
| `figures/deck/cross_target_benchmark.png` + `docs/cross_target_summary.md` | `make_cross_target_figure.py` | the same protocol refitted on CDK2 and thrombin — including where it fails |
| `docs/synthesis_feasibility.md` | `eval_synthesis.py` | heuristic retrosynthetic triage of the portfolio (no supplier check) |
| `figures/eval_dashboard.png`, `figures/docking_benchmark.png`, `figures/calibration.png`, `figures/baseline_study.png` | `make_dashboard.py`, `docking_report.py`, `make_calibration_figure.py`, `make_baseline_figure.py` | evaluation, oracle validation, calibration, baseline comparison |
| `docs/deck.pdf` | `make_deck.py` | 16-slide defence deck; the build fails if a slide overflows |

## Licence

Apache-2.0 for this code. Third-party tool and database licences are recorded per entry in
`registry/tools.yaml`, generated by `scripts/verify_registry.py`.
