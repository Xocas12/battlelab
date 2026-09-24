--[[
battlelab CMO entry point.

In the scenario editor create two events (see cmo/SETUP.md):
  1. "BL Init"  - trigger: Scenario Loaded   - action (Lua):
        ScenEdit_RunScript('battlelab/bl_run.lua')
  2. "BL Tick"  - trigger: Regular Time, every 1 minute, repeatable - action (Lua):
        BL.tick()

Before the first batch, run BL.selftest(BL_HOSTOMEL) from the Lua console.
]]
ScenEdit_RunScript('battlelab/bl_core.lua')
ScenEdit_RunScript('battlelab/bl_hostomel.lua')
ScenEdit_RunScript('battlelab/bl_design.lua')      -- written by `battlelab cmo-export`

-- Batch settings -------------------------------------------------------------
BL.cfg.run_hours = 46          -- replication length (game hours)
BL.cfg.settle_hours = 2        -- 46 + 2 = 48 h: every run starts at the same local time
BL.cfg.end_when_done = false
-- Scenario settings you must fill in once for your database build:
-- BL_HOSTOMEL.cfg.shell_warhead_dbid = <HE artillery warhead DBID>

BL.start(BL_HOSTOMEL, BL_DESIGN)
