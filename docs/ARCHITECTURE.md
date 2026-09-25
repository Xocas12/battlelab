# Architecture

## Layers

```
 scenario YAML  ──lint──►  Scenario ──build(params, seed, run)──► World + [Mechanic...]
      ▲                        │                                        │
  sources, anchors,        ParamSpace ──sample(seed, run)──► params     Engine.run()
  factor bundles               │                                        │
                               ▼                                        ▼
                         experiment.py  ── batches / swaps / sweeps ──► DataFrame (p.*, m.*)
                               │                                        │
                               └─► cmo.export_design ─► bl_design.lua   │
                                        CMO + bl_core/bl_<plugin>.lua ──┤ CSV (same schema)
                                                                        ▼
                                                analysis.py (+ plots.py) — one code path
```

The engine never reads YAML and the analysis never knows which engine produced a row.

## The world

`World` holds zones, units, sides, the clock, an event log, a per-turn `scratch` blackboard, a per-run `persist` store and named RNG streams.

* **Zones** are areas (airfield, bridgehead, ridge), not hexes. A zone may carry a `Runway` (obstacles and craters, both 0..1; usable = (1−obstacles)(1−craters)). Control is the single side with active units present, `contested` if both, unchanged if empty.
* **Units** have strength (personnel-equivalents), quality, a `dug_in` multiplier used when defending, a posture (defend/attack), a status (pending, active, withdrawn, broken, destroyed, cancelled) and a `Morale` block (base hazard, ammunition exhaustion time, immediate-withdrawal ratio, commitment time, what a break means, and an optional command decision cycle: `decision_h`, `comms_loss`, `fog`, `night_moves`).
* **Sides** have a role (attacker/defender), an `AirPosture` (CAS multiplier, suppression of enemy fires, interdiction, ingress and approach losses, night limitation) and a `doctrine` dict (risk tolerance, landing on a contested field, clearance and demolition rates, hasty-defence bonus).

## The turn sequence

Every `dt` hours each mechanic runs in phase order, like the sequence of play on a game's player aid card:

| Phase | Mechanic | What it does |
|---|---|---|
| SCHEDULE (0) | `Arrivals` | brings units on; air-delivered units lose aircraft (binomial) and a drop-zone fraction |
| AIR (10) | `AirSituation` | per-side CAS/suppression/interdiction for this turn, scaled at night if day-only |
| FIRES (20) | `Fires` | effective fire intensity (minus enemy suppression); cratering of runways the firer does not hold |
| COMBAT (30) | `Combat` + resolver | effective strength per side per contested zone; losses from the resolver |
| MORALE (40) | `MoraleCheck` | hazard of leaving the fight; outmatched, commitment-expired, collapse and forced-retreat exits; for units with a command cycle, the fight-or-leave hazard is judged by the commander at decision points on a possibly blind picture, and orders may wait for darkness |
| CONTROL (50) / AFTER_CONTROL (51) | `Control`, `FirstControlTracker` | zone ownership; hasty defence on capture; first-control times |
| ENGINEERING (60) | `RunwayEngineering` | obstacle clearance or demolition by the controller |
| AIRLIFT (70) | `Airlift` | go/no-go rule (threshold or logistic, on a possibly lagged risk estimate) and landings (waves or shuttle), optionally onto a contested field |
| RECORD (90) | `Outcome` | metrics |

`Mechanic` is the whole contract: `phase`, `setup(world)`, `step(world)`, `finalize(world)`. Mechanics communicate only through world state, `scratch` (per turn) and `persist` (per run).

## Randomness

* **Parameters:** for run *i* with seed *s*, parameter *k* gets u = U(0,1) from `SeedSequence([s, i, crc32(k)])` and its value is `dist.ppf(u)`. Replacing one parameter's distribution (a factor swap, a sweep point) leaves every other parameter's value in run *i* unchanged.
* **Process noise:** each component draws from its own stream (`world.rng("combat")`, `"morale"`, `"command"`, `"ingress"`, `"airlift"`, `"airlift_decision"`, `"crt"`), seeded from (seed, run, stream name). Adding a mechanic with a new stream does not perturb the others.
* **Process independence:** nothing may depend on the iteration order of a `set` of strings (hash randomisation differs per process); sides in a contested zone are sorted.

## Scenarios

YAML sections: `clock`, `sources`, `parameters`, `sides`, `zones`, `units` (with optional `arrive`), `fires`, `airlift`, `mechanics`, `outcome`, `factors`, `anchors`. A string `"$name"` anywhere in the structural sections is replaced by the sampled value of parameter `name` (rounded for integer fields such as `aircraft`). `lint()` checks the schema (unknown and missing keys and enum values per section, with paths; `SCHEMA` is derived from the spec dataclasses), references, provenance, sides, zones, factor membership and anchor metrics. `lint_pair()` checks that two scenarios' factor bundles match before they are swapped. `mechanics.go_no_go` selects the air-landing rule; `with_resolver` and `with_go_rule` build structural variants.

## Experiments and analysis

* `run_batch` → one row per run (`p.*` parameters, `m.*` metrics), optionally in parallel.
* `factor_swap(home, away)` → full factorial over factor bundles (2^k configurations, same seeds throughout), `SwapResult`.
* `analysis.shapley` → exact Shapley values of the swap game; `shapley_table` adds bootstrap intervals over runs (Monte Carlo noise only).
* `analysis.check_anchors` → per-anchor and joint share of runs that reproduce history.
* `analysis.abc_posterior` → rejection calibration: prior vs posterior of every sampled parameter given the anchors.
* `analysis.screen` → first-order variance share per parameter (binned), with its noise floor.
* `analysis.compare_backends` → run-by-run comparison of two result tables (native vs CMO) on shared draws.
* `report.run_report` → the standard pipeline over all scenarios and `results/SUMMARY.md`; every statement in it is computed from the saved tables.

## CMO backend

`cmo.export_design` writes `BL_DESIGN` (per-run parameter values and a per-run PRNG seed) as a Lua file. In CMO, `bl_core.lua` snapshots the pristine scenario, then loops: spawn from the template via the plugin's `mutate()` (cull, modify or defer each unit), call the plugin's `on_tick()` every game minute, call `evaluate()` after `run_hours`, write a CSV row, delete everything, wait `settle_hours`, repeat. The plugin (`bl_hostomel.lua`) maps factor parameters to things CMO can represent (surviving SAMs, helicopters in the lift, garrison size and proficiency, reinforcement timing and size) and scripts what CMO does not model (airfield control, runway obstruction, the Il-76 release rule, runway shelling via `ScenEdit_AddExplosion`).
