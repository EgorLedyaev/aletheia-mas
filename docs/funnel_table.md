# Candidate funnel (generated — do not edit by hand)

Produced by `python scripts/funnel_report.py` from the claims ledger of each run.
Every document that quotes funnel numbers must match this table; `tests/test_funnel.py` enforces it.

| stage | S07 | S08 |
|---|---|---|
| raw proposals from the generators | 86 | 126 |
| unique after cross-generator dedup | 86 | 126 |
| removed by the hazard gate | 0 | 0 |
| candidates entering the cheap-filter gate | 86 | 126 |
| survive the cheap-filter gate | 5 | 104 |
| rejected by the cheap-filter gate | 81 | 22 |
| scored by the activity model | — | 104 |
| of those, outside the applicability domain | — | 11 |
| docked with AutoDock Vina | — | 8 |
| on the Pareto front | 2 | 8 |
| chemotype clusters (Butina) | 3 | 38 |
| selected into the portfolio | 5 | 8 |

## Run identity

| | S07 | S08 |
|---|---|---|
| run id | `run-20261113T013352-84470c` | `run-20261113T013401-4077d6` |
| generator seed | `user molecule from the query` | `COc1cc2ncnc(Nc3cccc(Br)c3)c2cc1OC` |
| per-generator counts | G1=36, G3=40, G4=10 | G1=37, G2=40, G3=40, G4=9 |

## Cheap-filter gate thresholds (identical in both runs)

| parameter | value |
|---|---|
| `max_lipinski_violations` | 1 |
| `max_sa_score` | 6.0 |
| `max_structural_alerts` | 1 |
| `min_qed` | 0.3 |

## Why the two runs differ

Both runs generated the same *number* of unique molecules (a coincidence: 36+40+40+10 and 37+40+40+9 both total 126), but from different seeds — S07 is seeded with the erlotinib SMILES given in the query, S08 with the most potent retrieved active, because its query names no molecule. Different seed, different candidate population, different survival rate at an identical gate.
