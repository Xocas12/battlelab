# Pilot kit: probe this evening, Hostomel pilot overnight

Everything here is pre-generated, so the laptop needs CMO only (no Python). What cannot be done without CMO has been tested against the mock CMO API: building the scenario from an empty one, the self-test, and full replications through the real `bl_run.lua` entry point (`cmo/tests/test_build.lua`).

| File | What |
|---|---|
| `bl_design.lua` | 20 Hostomel replications (runs 0-19, seed 1), from `battlelab cmo-export scenarios/hostomel_2022.yaml -n 20` |
| `native_hostomel_runs0-19.csv` | the native engine's results for the same 20 runs and draws, for `battlelab compare-backends` |

## Evening: probe (5 minutes, no clock)

1. Copy `cmo/lua/battlelab/` into `<CMO>/Lua/battlelab/`.
2. Open any scenario with an airbase that hosts aircraft and at least one ground unit. Don't save it afterwards.
3. Lua console:
   ```lua
   ScenEdit_RunScript('battlelab/bl_probe.lua')
   BL_PROBE_WRITE = true
   ScenEdit_RunScript('battlelab/bl_probe.lua')
   ```
4. Copy all `BLPROBE|` lines and send them back. If they show a field the harness reads wrongly, it gets fixed before the overnight run, so send them as early as you can.

## Before the overnight run: build the scenario (scripted, about 15 minutes)

You do not place anything by hand. `bl_build_hostomel.lua` builds the whole scenario: sides, the Hostomel airfield with four runway segments and its polygon, garrison, counterattack, SAMs, artillery, 20 Mi-8s with 20 VDV squads, 18 Il-76s at Pskov, the relief column, both missions, both harness events and the start time.

1. Edit `<CMO>/Lua/battlelab/bl_build_db.lua`: replace each `nil` with a DBID from your database (Database Viewer). This is the only step that needs you: DBIDs differ between database versions.
2. File > New scenario (pick the database whose DBIDs you used). Open the Lua console and run:
   ```lua
   ScenEdit_RunScript('battlelab/bl_build_hostomel.lua')
   ```
3. Every `BLBUILD|` line should say OK or SKIP. A FAIL line names the step; do that one step by hand in the editor (the event wiring is the most likely candidate, since those functions have not been tried on a live build yet).
4. **Save straight away** (File > Save As, e.g. `battlelab_hostomel.scen`), before starting the clock. This saved file is the pristine template; the "scenario loaded" event starts a batch, which clears the map.
5. Send the `BLBUILD|` lines back if anything failed.

## Overnight

1. Copy `bl_design.lua` from this folder to `<CMO>/Lua/battlelab/bl_design.lua`.
2. Load the saved scenario (this starts the batch), open the Lua console and run `BL.selftest(BL_HOSTOMEL)`. Every line should say OK; it checks the template the batch captured.
3. Start the clock at the highest compression the laptop sustains and leave it.

Each replication is 48 game hours. A row is written as each one finishes, so whatever completes overnight is usable; you do not need all 20. If the laptop sleeps, the batch simply stops there.

## Morning

Send back `battlelab_results.csv` from the scenario's folder. If file output was blocked (the probe's `file_write` line says so), run `BL.dump_results()` in the Lua console and send the console text instead. Then:

```bash
battlelab compare-backends cmo/pilot/native_hostomel_runs0-19.csv battlelab_results.csv
```
