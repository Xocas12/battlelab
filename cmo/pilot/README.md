# Pilot kit: probe this evening, Hostomel pilot overnight

Everything here is pre-generated, so the laptop needs CMO only (no Python).

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

## Before the overnight run: build the scenario (the long part)

The pilot needs a Hostomel scenario built in the CMO editor with the unit names from `cmo/SETUP.md` section 2 (`RU_HELO_T_..`, `RU_IL76_..`, `UA_NG_..`, `UA_CA_..`, `BL_RWY_..`, reference points `BL_AF_1..4`, mission `BL Airlift`, airbase `Hostomel Airport`) and the two events from section 3. Keep it lean for a slow laptop: a few units per force are enough, since the harness scales counts from `*_nominal` in `bl_hostomel.lua`. Set `BL_HOSTOMEL.cfg.shell_warhead_dbid` in `bl_run.lua` (section 4), or runway shelling is skipped.

## Overnight

1. Copy `bl_design.lua` from this folder to `<CMO>/Lua/battlelab/bl_design.lua`.
2. Load the saved (pristine) scenario, open the Lua console and run `BL.selftest(BL_HOSTOMEL)`. Every line should say OK.
3. Start the clock at the highest compression the laptop sustains and leave it.

Each replication is 48 game hours. A row is written as each one finishes, so whatever completes overnight is usable; you do not need all 20. If the laptop sleeps, the batch simply stops there.

## Morning

Send back `battlelab_results.csv` from the scenario's folder. If file output was blocked (the probe's `file_write` line says so), run `BL.dump_results()` in the Lua console and send the console text instead. Then:

```bash
battlelab compare-backends cmo/pilot/native_hostomel_runs0-19.csv battlelab_results.csv
```
