# battlelab

A Monte Carlo framework for asking structured "why did this battle go the way it did?" questions, with two engines behind one analysis layer:

1. **Native engine** (Python). A board-game-shaped model: named zones instead of hexes, units with strength/quality/posture, and a fixed turn sequence (arrivals, air, fires, combat, morale, control, engineering, airlift, record). Mechanics are small pluggable classes. About 3.5 ms per 48-hour replication, so tens of thousands of runs are cheap.
2. **CMO harness** (Lua). Runs many replications of a Command: Modern Operations scenario inside one game session on the public (Steam) edition, driven by the *same* parameter draws, and writes results in the *same* CSV schema.

Both engines feed the same analysis code: summaries, historical-anchor checks, rejection calibration, sensitivity screening, and Shapley decomposition of cross-battle "factor swaps".

## Why it is built this way

The failure mode of a quick battle model is untraceable numbers: parameters picked to make the answer look right, no record of where they came from, and a single structure presented as if it were the truth. The framework is designed against that:

* **Scenarios are data.** Every parameter lives in the scenario YAML with a distribution, a source key or an explicit `assumption: true`, a confidence level and a note. `battlelab lint` refuses to run a scenario with an unsourced, unflagged parameter.
* **History is a test, not a target.** Each scenario lists *anchors* (things that actually happened). `battlelab anchors` reports how typical history is inside the model. `battlelab calibrate` shows which parameters the historical record actually constrains.
* **Structure is a variable.** Combat resolution is pluggable (stochastic Lanchester or a board-game CRT) so conclusions can be checked for dependence on the attrition model.
* **Common random numbers.** Each parameter's draw depends only on (seed, run, parameter name), so swapping one factor never reshuffles the others. This is what makes factor-swap differences and Shapley values meaningful at modest run counts.
* **Everything is traceable.** Saved results carry a manifest with scenario fingerprints, seeds and overrides.

## Install

```bash
pip install -e .[dev]        # numpy, pandas, pyyaml, matplotlib; pytest for tests
pytest -q                    # 23 tests; the Lua harness tests need lua5.3 on PATH
```

## Quick start

```bash
battlelab lint scenarios/*.yaml
battlelab trace scenarios/hostomel_2022.yaml --run 3          # one run as a wargame log
battlelab run scenarios/hostomel_2022.yaml -n 4000 --out results/
battlelab anchors scenarios/maleme_1941.yaml -n 2000          # is history typical in the model?
battlelab calibrate scenarios/maleme_1941.yaml -n 8000        # which params does history constrain?
battlelab screen scenarios/hostomel_2022.yaml -n 4000         # which params drive the outcome?
battlelab swap scenarios/hostomel_2022.yaml scenarios/maleme_1941.yaml --both -n 1000 --out results/
battlelab sweep scenarios/hostomel_2022.yaml --grid risk.tolerance=0:0.4:9 \
                --grid denial.t_fires=1:12:12 -n 400 --out results/
battlelab run scenarios/hostomel_2022.yaml --set risk.tolerance=0.2     # counterfactual
```

## Layout

```
battlelab/
  params.py        distributions (inverse CDF), provenance, CRN sampling
  state.py         World, Unit, Zone, Runway, Side, AirPosture, event log, RNG streams
  engine.py        Phase enum + Engine (turn sequence) + Mechanic base class
  mechanics/       movement.py (arrivals, air, fires), combat.py (resolvers, morale),
                   airfield.py (control, engineering, airlift, outcome)
  scenario.py      YAML -> World + mechanics; $parameter references; lint
  experiment.py    batches, factor swaps, sweeps, manifests
  analysis.py      Wilson CIs, Shapley (+bootstrap), anchors, ABC calibration, screening
  plots.py         standard figures
  cmo.py           export designs to Lua, ingest CMO results
  cli.py           the `battlelab` command
scenarios/         hostomel_2022.yaml, maleme_1941.yaml (the "airhead" family)
cmo/lua/battlelab/ bl_core.lua (replication engine), bl_hostomel.lua (plugin), bl_run.lua
cmo/tests/         mock_cmo.lua + test_harness.lua (offline tests of the harness)
docs/              ARCHITECTURE.md, MODELING_STANDARDS.md
cmo/SETUP.md       how to wire the harness into a CMO scenario
```

## Extending

**New battle in an existing family.** Copy a scenario YAML, keep the parameter names, change values and sources, write anchors, run `lint` and `anchors`. Factor swaps with the other members of the family work immediately.

**New mechanic.** Subclass `Mechanic`, pick a `Phase`, implement `step(world)` (and `setup`/`finalize` if needed), keep per-run state in `world.persist`, draw randomness from `world.rng("<your stream>")`, and emit events with `world.emit(...)` so `trace` shows what it did. Wire its configuration into `Scenario.build`. Add a test that checks an invariant or a known limit.

**New combat model.** Implement `Resolver.resolve(world, zone, eff, attacker) -> losses` and register it in `RESOLVERS`. Scenarios select it with `mechanics.combat.resolver`.

**New family** (e.g. river crossing, naval engagement). New mechanics plus a new outcome spec and metric names; the engine, parameter system, experiments and analysis do not change.

## CMO in one paragraph

Build the scenario in the CMO editor using the naming conventions in `cmo/SETUP.md`, add two events (scenario-loaded runs `bl_run.lua`, a one-minute regular-time event calls `BL.tick()`), and run `BL.selftest(BL_HOSTOMEL)` in the Lua console. Generate a design with `battlelab cmo-export scenarios/hostomel_2022.yaml -n 200 --out "<CMO>/Lua/battlelab/bl_design.lua"`, load the scenario, set maximum time compression and let it run. Each 48-game-hour cycle is one replication. Feed the resulting CSV (or a pasted console log) to `battlelab cmo-ingest`.

## Current results and handoff

First-draft results, with every number traced to a file, are in `results/SUMMARY.md`; `scripts/reproduce.sh` regenerates them. `CLAUDE.md` holds the working rules, known issues and the prioritised backlog for further development.

## Status and honest limits

* The native engine is tested (determinism, CRN independence, resolver expectations, invariants over hundreds of runs, lint, Shapley identities).
* The CMO harness is tested only against a mock of the CMO Lua API built from the published documentation. Some unit-wrapper fields it reads (`base`, `damage`, `loadoutdbid`, `group`) and the `course` field of `ScenEdit_SetUnit` are used defensively but have not been verified in a live CMO build. Run the self-test first.
* The combat, morale and landing-risk constants are flagged assumptions. The CRT table is a structural alternative, not a calibrated one.
* See `docs/MODELING_STANDARDS.md` for how results should and should not be read.
