# Running battlelab replications in Command: Modern Operations

The harness runs a batch of replications inside one CMO session using only functions documented as available in all editions (no Professional Edition features). It has been tested against a mock of the CMO Lua API (`cmo/tests/`), **not yet inside a live CMO build**, so start with the self-test and a three-run batch.

Licence note: the Steam/Matrix edition is licensed for personal use. Professional or commercial analysis needs Command: Professional Edition, which also offers headless batch execution.

## 1. Install the scripts

Copy `cmo/lua/battlelab/` into your CMO installation's `Lua` folder, so you have `<CMO>/Lua/battlelab/bl_core.lua` etc. `ScenEdit_RunScript` resolves paths relative to `<CMO>/Lua`. On some older Steam builds the working folder was `GameMenu_CMANO/Lua` instead; if `RunScript` cannot find the file, try there.

## 2. Build the scenario once, with these names

The plugin finds units by name prefix. Everything else in the scenario is left alone and simply respawned each replication.

| Prefix | Side | What | Parameter(s) driving it |
|---|---|---|---|
| `RU_HELO_T_01..` | Russia | transport helicopters carrying the assault force (loaded, on their mission) | `mass.aircraft` keeps the first N |
| `RU_HELO_A_..` | Russia | attack helicopters | (CMO simulates) |
| `RU_IL76_01..18` | Russia | Il-76s at their base, assigned to mission `BL Airlift` (a ferry/transport mission to Hostomel) | release rule: `risk.tolerance`, `ctx.wave1_t`, `ctx.wave2_t`, `air.att.approach_loss` |
| `RU_COL_..` | Russia | ground column | spawned at `ctx.t_relief` and ordered to the airfield |
| `UA_NG_01..` | Ukraine | National Guard garrison inside the airfield | `hold.strength` (count), `hold.quality` (proficiency) |
| `UA_CA_01..` | Ukraine | counterattack force, placed where it forms up | `response.strength` (count), `response.t_ca` (spawn time) |
| `UA_ART_..` | Ukraine | artillery (optional) | scripted fires start at `denial.t_fires` and stop if all are destroyed |
| `UA_SAM_..` | Ukraine | air defence that SEAD may have removed | each survives with probability 1 − `air.att.suppression` |
| `BL_RWY_1..` | Ukraine | runway segment facilities of the airbase | usable fraction; shelled by scripted fires |
| `BL_AF_1..4` | Russia | reference points outlining the airfield | control rule polygon |

Also required: the airbase unit/group named `Hostomel Airport` (Ukraine side) and the Russian mission `BL Airlift`. Names are configurable at the top of `bl_hostomel.lua` (`BL_HOSTOMEL.cfg`). Unit names must be unique: missions and targets are re-linked by name after each respawn.

Scale the forces so that the `*_nominal` values in `cfg` mean "everything present": with `garrison_nominal = 200`, a draw of `hold.strength = 150` keeps 75% of the `UA_NG_` units.

## 3. Add two events in the Event Editor

1. **BL Init**: trigger *Scenario Loaded*; action *Lua script*: `ScenEdit_RunScript('battlelab/bl_run.lua')`
2. **BL Tick**: trigger *Regular Time*, every 1 minute; repeatable; action *Lua script*: `BL.tick()`

Save the scenario. This saved file is the pristine template: always start a batch from it, not from a save game made mid-batch (the harness refuses to start if its KeyStore says a batch already ran; `BL.reset_progress()` clears that).

## 4. Configure once for your database

In `bl_run.lua`, set `BL_HOSTOMEL.cfg.shell_warhead_dbid` to the DBID of an artillery HE warhead from your database (look it up in the DB viewer). Without it, the harness still runs but the runway is never shelled, so the DENIAL factor only acts through obstruction timing.

## 5. Self-test

Load the scenario, open the Lua console and run:

```lua
ScenEdit_RunScript('battlelab/bl_core.lua')
ScenEdit_RunScript('battlelab/bl_hostomel.lua')
BL.selftest(BL_HOSTOMEL)
```

Every line should say OK. The file-output line tells you whether Lua `io` is permitted in your build; if not, results go to the KeyStore and the console instead (see step 8).

## 6. Generate a design

```bash
battlelab cmo-export scenarios/hostomel_2022.yaml -n 3 --out "<CMO>/Lua/battlelab/bl_design.lua"
```

Start with 3 runs to measure how long one 48-game-hour replication takes at your maximum time compression. Then scale. Designs for factor swaps: `--swap-from scenarios/maleme_1941.yaml --factors RISK,HOLD`.

## 7. Run

Load the scenario, start it, set the highest time compression your machine sustains (the public edition cannot set compression from Lua), and leave it. Each replication is `run_hours` (46) of fighting plus `settle_hours` (2) of an empty map so weapons in flight expire; 48 hours keeps every replication at the same local time of day. A pop-up says when the batch is complete.

## 8. Collect and analyse

* If file output works: `battlelab_results.csv` appears in the scenario's folder.
* Otherwise: in the Lua console run `BL.dump_results()`, copy the console text into a file.

Both are accepted by:

```bash
battlelab cmo-ingest battlelab_results.csv --scenario scenarios/hostomel_2022.yaml
```

The rows carry the same `p.*` parameter columns as the native engine's output (same draws for the same seed and run index), so you can compare CMO and native outcomes run by run.

## Known gaps to check in a live build

* Unit-wrapper fields read defensively: `base.name` (landed Il-76 detection, hosted aircraft respawn), `damage.dp`/`startdp` or `dp_percent` (runway health), `loadoutdbid`, `mission.name`, `group`. If a field is missing the harness falls back (e.g. runway health reads as 1.0), so check `runway_end` and `t_first_landing` in a trial batch.
* `ScenEdit_SetUnit({course=...})` for ground units (counterattack and column movement).
* Whether flipping the airbase side with `ScenEdit_SetUnitSide` lets the Il-76 mission land there in your build. If not, the fallback is to pre-place a Russian-side "landing strip" facility and use it as the mission destination.
* Ground combat in CMO is abstract; the airfield control rule (sole occupation for 15 minutes) is the harness's, not CMO's.
