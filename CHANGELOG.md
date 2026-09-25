# Changelog

## 0.2.0 (2026-09-24)

Model changes (each reduces exactly to 0.1.0 behaviour at its default; checked run-for-run):

* **Command decision cycles** (`Morale.decision_h`, `comms_loss`, `fog`, `night_moves`). The commander evaluates the fight-or-leave hazard at decision points, possibly without reports (then assuming at least `fog` casualties), and a withdrawal order can wait for darkness. Four new HOLD parameters in every airhead scenario. Maleme uses the NZH account of the 22nd Battalion losing contact with its forward companies and withdrawing overnight.
* **Selectable go/no-go rule** (`mechanics.go_no_go`): the hard `threshold` (default) or `logistic` acceptance (one nerve draw per wave or sortie), both optionally on a risk estimate lagged by `info_lag_h`. New family constants `mech.go_width` and `mech.info_lag_h`.
* **Landing on a contested field** (doctrine `land_contested`, `airlift.contested_risk`): a wave may land into a fight at extra risk, and its troops attack. New RISK parameter `risk.land_contested`, new family constant `mech.contested_risk`.
* **Fix: cross-process nondeterminism.** Combat iterated over a set of side ids, so which side received which Lanchester draw depended on per-process string hashing. 0.1.0 results were statistically, but not exactly, reproducible.

New scenario: **Ypenburg 1940** (third member of the airhead family; thinly sourced, see CLAUDE.md).

### CMO backend

Not yet run in a live CMO build; everything below passes against the mock CMO API.

* `bl_probe.lua`: checks every API assumption in a live build from any scenario, without running the clock.
* `bl_build_hostomel.lua` + `bl_build_db.lua`: builds the whole Hostomel scenario from an empty one; the user only supplies DBIDs.
* Fix: Russian air-assault troops were never put on the ground in CMO (respawned helicopters carry no cargo). They are now scripted RU_VDV_ squads unloaded by each helicopter that reaches the airfield; new metric `vdv_delivered`.
* Fix: `BL.selftest` failed in the documented flow (after the scenario-loaded event had started a batch and emptied the map).
* `cmo-export --start`, a 20-run pilot kit in `cmo/pilot/`, and an end-to-end mock test (build, selftest, replications through `bl_run.lua`).

### Tooling

Schema lint with paths; `battlelab report` (writes results/SUMMARY.md), `resolvers`, `compare-backends`; `--go-rule`, `--set` and `--tag` on every experiment command; one process pool per swap or sweep (3.6x faster on 4 cores); CI with ruff, mypy, pytest and the Lua harness.

Results (all in results/, regenerated with `scripts/reproduce.sh`, N = 1000, seed 1):

| | 0.1.0 | 0.2.0 |
|---|---|---|
| Maleme joint anchors, Lanchester | 0.40 | 0.68 |
| Maleme joint anchors, CRT | 0.09 | 0.13 |
| Hostomel joint anchors, Lanchester / CRT | 0.60 / 0.50 | 0.60 / 0.50 |
| Ypenburg joint anchors, Lanchester / CRT | - | 0.04 / 0.04 |
| Hostomel with Maleme's factors, Lanchester | 0.33 -> 0.75 | 0.33 -> 0.74 |
| Hostomel with Maleme's factors, CRT | 0.36 -> 0.41 | 0.36 -> 0.34 |
| Maleme with Hostomel's factors, Lanchester | 0.69 -> 0.00 | 0.67 -> 0.00 |
| Maleme with Hostomel's factors, CRT | 0.40 -> 0.01 | 0.24 -> 0.01 |

Findings that survive the changes: HOLD and RISK remain the two largest Shapley contributions between Hostomel and Maleme, with the same signs, under both resolvers and under all three go/no-go rules (SUMMARY sections 3 and 4). Hostomel's Shapley values for Maleme's factors move by at most 0.03 when the go/no-go rule changes, so the swap conclusions do not rest on the hard threshold. The zero single-swap of DENIAL is a property of the rule and becomes 0.02 under the logistic rule. Changed: under CRT, the Maleme baseline fell from 0.40 to 0.24. The likely cause (not yet isolated) is that the command cycle holds the NZ battalion on the field until dark, and the CRT's high attacker attrition then wears the paratroops down first.

## 0.1.0 - first draft (2026-09-24)

* Native engine: board-game turn sequence, pluggable mechanics (arrivals and insertion, air situation, fires, combat with Lanchester or CRT resolver, morale, control, runway engineering, airlift, outcome).
* Scenario YAML with per-parameter provenance and lint; `airhead` family with Hostomel 2022 and Maleme 1941.
* Experiments: batches, full-factorial factor swaps, sweeps, manifests. Analysis: Wilson intervals, exact Shapley with bootstrap, anchor checks, ABC rejection calibration, screening.
* CMO harness (Lua): in-session replication loop, Hostomel plugin, self-test; design export and result ingest in Python. Tested against a mock CMO API only.
