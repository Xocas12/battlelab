--[[ End to end against the mock: build the Hostomel scenario from an empty world with
bl_build_hostomel.lua, check it, then run a 3-replication batch on it with the real
bl_run.lua entry point and the Python-exported pilot design.
usage: lua5.3 tests/test_build.lua <lua_dir> <out_dir> <design.lua> ]]
local lua_dir, out_dir, design_file = arg[1], arg[2], arg[3]
local here = arg[0]:match("(.*/)") or "./"
dofile(here .. "mock_cmo.lua")
MOCK.lua_dir = lua_dir
_scenariofolder_ = out_dir
local failures = 0
local function check(c, m) if not c then failures = failures + 1 end
  io.stdout:write((c and "PASS " or "FAIL ") .. m .. "\n") end

-- 1. refuses to build without DBIDs ------------------------------------------------
BL_BUILD_DB = {}
local b = dofile(lua_dir .. "/battlelab/bl_build_hostomel.lua")
check(MOCK.count_all() == 0 and b.fails == 1, "no DBIDs: stops before changing anything")

-- 2. builds with DBIDs --------------------------------------------------------------
BL_BUILD_DB = {airfield = 1, runway_segment = 2, ua_infantry = 10, ua_sam = 12,
               ua_artillery = 13, ru_infantry = 50, ru_mech = 40, mi8 = 30, mi8_loadout = 300,
               il76 = 31, il76_loadout = 310, shell_warhead = 999}
b = dofile(lua_dir .. "/battlelab/bl_build_hostomel.lua")
check(b.fails == 0, "build reports no failures (" .. b.fails .. ")")
local function n(prefix) return #MOCK.live(prefix) end
check(n("RU_HELO_T_") == 20 and n("RU_IL76_") == 18, "20 helicopters, 18 Il-76")
check(n("UA_NG_") == 8 and n("UA_CA_") == 6 and n("RU_VDV_") == 20, "garrison, counterattack, VDV")
check(n("BL_RWY_") == 4 and MOCK.rps["BL_AF_4"] ~= nil, "runway segments and airfield polygon")
check(MOCK.missions["BL Airlift"] and MOCK.missions["BL Airlift"].isactive == false,
      "BL Airlift exists and starts inactive")
check(#MOCK.events["BL Tick"].triggers == 1 and #MOCK.events["BL Init"].actions == 1,
      "events wired")
local before = MOCK.count_all()
b = dofile(lua_dir .. "/battlelab/bl_build_hostomel.lua")
check(MOCK.count_all() == before, "re-running the build adds nothing")

-- 3. the real entry point on the built scenario --------------------------------------
-- bl_run.lua loads battlelab/bl_design.lua; point it at the pilot design instead.
local real_run = ScenEdit_RunScript
function ScenEdit_RunScript(path)
  if path == "battlelab/bl_design.lua" then dofile(design_file) return end
  real_run(path)
end
ScenEdit_RunScript(MOCK.actions["BL run harness"].ScriptText:match("'(.-)'"))
BL.cfg.verbose = false
check(BL_HOSTOMEL.cfg.shell_warhead_dbid == 999, "bl_run.lua picks up shell_warhead from the DB file")
local st_ok = BL.selftest(BL_HOSTOMEL)
if not st_ok then for _, l in ipairs(MOCK.printed) do if l:match("selftest.*FAIL") then io.stdout:write(l, "\n") end end end
check(st_ok, "selftest passes on the built scenario")
while #BL_DESIGN.runs > 3 do table.remove(BL_DESIGN.runs) end
local AF_LAT, AF_LON = 50.6035, 30.1919
local guard = 0
while BL.state.phase ~= "done" and guard < 3000 * 4 do
  MOCK.now = MOCK.now + 60
  local ctx = BL.state.ctx
  if BL.state.phase == "running" and ctx.elapsed_h >= 0.75 and not ctx.state._arrived then
    ctx.state._arrived = true                  -- helicopters reach the field
    for _, u in ipairs(MOCK.live("RU_HELO_T_")) do u.latitude, u.longitude = AF_LAT, AF_LON end
  end
  BL.tick()
  guard = guard + 1
end
check(BL.state.phase == "done", "3 replications complete")
local f = io.open(out_dir .. "/battlelab_results.csv")
local rows = 0
local delivered = 0
local header
for ln in f:lines() do
  if not header then header = {}
    for c in ln:gmatch("[^,]+") do header[#header + 1] = c end
  else
    rows = rows + 1
    local k = 0
    for c in (ln .. ","):gmatch("([^,]*),") do
      k = k + 1
      if header[k] == "m.vdv_delivered" then delivered = delivered + (tonumber(c) or 0) end
    end
  end
end
f:close()
check(rows == 3, "3 result rows")
check(delivered > 0, "VDV delivered in the built scenario (" .. delivered .. ")")
if failures > 0 then io.stdout:write(failures .. " FAILURE(S)\n") os.exit(1) end
io.stdout:write("BUILD END-TO-END PASSED\n")
