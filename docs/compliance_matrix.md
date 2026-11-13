# Compliance matrix — ХИМБИО-ХАКАТОН «СИНТЕЗ» 2026, Case 1

Every official requirement from the case text (`СИНТЕЗ_кейсы`, pp. 2–3) mapped to the evidence in
this repository. "Evidence" means a file, a figure or a run id that can be opened during the
defence.

## 4. Пользовательские сценарии — ≥ 3 scenarios

| requirement | status | evidence |
|---|---|---|
| не менее трёх сценариев «запрос → действия МАС → ожидаемый ответ» | **13 scenarios** (S01–S12 plus S05b, the docking degradation path) | `docs/scenarios/S01…S12_*.md`, generated from run logs by `aletheia/eval/scenarios.py:write_card` |
| сценарии отражают реальные возможности прототипа | 12/12 pass machine-checked invariants | `eval/final_suite.json`; `docs/evaluation_report.md` §1 |

## 5. Требования к прототипу

| requirement | status | evidence |
|---|---|---|
| **Несколько взаимодействующих агентов с определёнными функциями** | 12 agents with declared competences and typed contracts | `aletheia/agents/` (planner, safety, target_analyst, structure_analyst, chemistry_retriever, molecule_generator, property_agent, qsar_agent, docking_agent, ranker, critic, reporter); roles in `docs/architecture.md` §2 |
| **LLM — ключевой компонент управления или взаимодействия** | the LLM routes every request (intents + entity extraction), reviews safety, proposes structural edits and writes the interpretation; nothing executes before it classifies | `aletheia/agents/planner.py`, `agents/safety.py`, `agents/generator.py::_llm_edits`, `agents/reporter.py::_narrative`; backend recorded per run in `cost.llm_backend` |
| **Обработка запросов на естественном языке** | free-text in, structured answer out, EN and RU keyword routing | `python -m aletheia.cli ask "..."`; any scenario card, §"User request" |
| **Координация действий агентов** | two orchestration patterns over the same contracts, dependency ordering, parallel fan-out, time budget | `aletheia/orchestrator/supervisor.py`, `orchestrator/blackboard.py`; comparison in `docs/evaluation_report.md` §2 |
| **Интеграция внешних научных инструментов, моделей или баз данных** | 57 registered tools: RDKit, AutoDock Vina 1.2.7, Open Babel, scikit-learn, UniProtKB, RCSB PDB, AlphaFold DB, ChEMBL, PubChem | `python -m aletheia.cli tools`; `registry/tools.yaml` (16/16 entries VERIFIED with versions and licences) |
| **Формирование интерпретируемых ответов** | every value printed with its provenance badge, a claims appendix, a plan trace, a degradation section and a verification summary | `aletheia/core/render.py`; `runs/<run_id>.answer.md` |
| **Выполнение заявленных сценариев** | 12/12 | `eval/final_suite.json` |
| **Прозрачное различение реальных расчётов, предсказаний и гипотез** | four enforced tags: COMPUTED / PREDICTED / RETRIEVED / HYPOTHESIS, with contract validation per tag | `aletheia/core/provenance.py::Evidence._tag_requirements`; rendered in every answer |
| **Отсутствие вымышленных результатов** | claims ledger + blocking verifier: a numeric token that resolves to no tool output stops publication; HYPOTHESIS evidence may not carry a number | `aletheia/core/ledger.py`; 12/12 runs at 100% coverage; 7/7 red-team probes held (`docs/redteam_log.md`) |

## 6. Что представить на защите

| requirement | status | evidence |
|---|---|---|
| **Схема архитектуры: роли, взаимодействие, инструменты, потоки данных** | Mermaid source + exported PNG + written rationale (7 design decisions) | `docs/architecture.md`, `figures/architecture.png` |
| **Работающий прототип и демонстрация на ≥ 3 сценариях** | CLI + web UI; 13 scenarios runnable live or from cache | `make demo` / `.\scripts\demo.ps1`; `docs/demo_script.md` |
| **Описание сценариев: запрос, ожидаемый ответ, действия системы, фактический результат** | 12 cards; the "actual result" section is generated from the run log, never written by hand | `docs/scenarios/` |
| **Репозиторий: код, инструкция запуска, модели, инструменты, примеры результатов** | this repository | `README.md`, `Makefile`, `scripts/setup.ps1`, `models/qsar_CHEMBL203.pkl`, `tools/vina/`, `runs/`, `eval/` |
| **Краткая презентация: технические решения и ограничения** | 13 slides + speaker notes, limitations stated on their own slide | `docs/deck.md`, `docs/limitations.md` |

## Beyond the required minimum

| extra | evidence |
|---|---|
| automated evaluation harness with invariant checks | `aletheia/eval/scenarios.py`, `eval/harness.py` |
| two orchestration patterns benchmarked head-to-head | `docs/evaluation_report.md` §2 |
| four ablations (critic, single generator, guardrail, verifier) | `docs/evaluation_report.md` §3 |
| two baselines (plain LLM, single tool-using agent) with a traceability metric | `docs/evaluation_report.md` §4, `aletheia/eval/baselines.py` |
| redocking validation + decoy enrichment attached to every docking score | `eval/docking_validation.json`, `figures/docking_validation.png` |
| scaffold-split QSAR with mandatory baselines, conformal intervals, applicability domain | `figures/qsar_calibration.png` |
| four independent generators with per-generator novelty statistics | `figures/generator_comparison.png` |
| multi-objective Pareto ranking + diversity portfolio with P(≥1 hit) bounds | `aletheia/tools/ranking.py` |
| target identity check that blocks ID↔structure mismatches | scenario S11 |
| hazard screening of every generated structure + refusal audit log | `docs/safety_policy.md`, `logs/safety_events.jsonl` |
| independent red-team pass | `docs/redteam_log.md` |
| negative-results log | `docs/negative_results.md` |
| offline demo path with recorded LLM responses and cached tool results | `ALETHEIA_OFFLINE=1`, `cache/` |
| tool/licence registry verified programmatically | `registry/tools.yaml`, `scripts/verify_registry.py` |
| reproducibility manifest (versions, seeds, hashes) | `docs/reproducibility.md` |
