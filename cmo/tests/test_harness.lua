--[[
Offline test of the battlelab CMO harness against mock_cmo.lua.
usage: lua5.3 test_harness.lua <lua_dir> <out_dir> [design.lua|-] [--no-io]
Exit code 0 = all assertions passed.
]]
local lua_dir, out_dir, design_file, flag = arg[1], arg[2], arg[3], arg[4]
local here = arg[0]:match("(.*/)") or "./"
dofile(here .. "mock_cmo.lua")
MOCK.lua_dir = lua_dir
_scenariofolder_ = out_dir
local real_io = io                -- the test itself always keeps file access
if flag == "--no-io" then io = nil end   -- ...but the harness does not

local failures = 0
local function check(cond, msg)
  if not cond then failures = failures + 1 end
  real_io.stdout:write((cond and "PASS " or "FAIL ") .. msg .. "\n")
end

-- ---------------------------------------------------------------- world ----
local AF_LAT, AF_LON = 50.604, 30.192
local function add(t) return ScenEdit_AddUnit(t) end
add({type = "Facility", name = "Hostomel Airport", side = "Ukraine", dbid = 1, latitude = AF_LAT, longitude = AF_LON, group = "Hostomel Airport"})
for i = 1, 4 do
  add({type = "Facility", name = "BL_RWY_" .. i, side = "Ukraine", dbid = 2, latitude = AF_LAT + (i - 2.5) * 0.004, longitude = AF_LON, group = "Hostomel Airport"})
end
for i = 1, 10 do add({type = "Facility", name = string.format("UA_NG_%02d", i), side = "Ukraine", dbid = 10, latitude = AF_LAT + 0.001 * (i % 3), longitude = AF_LON + 0.002}) end
for i = 1, 6 do add({type = "Facility", name = string.format("UA_CA_%02d", i), side = "Ukraine", dbid = 11, latitude = AF_LAT - 0.15, longitude = AF_LON}) end
for i = 1, 3 do add({type = "Facility", name = "UA_SAM_" .. i, side = "Ukraine", dbid = 12, latitude = AF_LAT + 0.02 * i, longitude = AF_LON + 0.03}) end
for i = 1, 2 do add({type = "Facility", name = "UA_ART_" .. i, side = "Ukraine", dbid = 13, latitude = AF_LAT - 0.2, longitude = AF_LON - 0.1}) end
add({type = "Facility", name = "Bolshoy Bokov", side = "Russia", dbid = 20, latitude = 51.5, longitude = 29.9})
add({type = "Facility", name = "Pskov", side = "Russia", dbid = 21, latitude = 57.78, longitude = 28.4})
MOCK.add_mission("Russia", "BL Airlift")
for i = 1, 20 do add({type = "Aircraft", name = string.format("RU_HELO_T_%02d", i), side = "Russia", dbid = 30, latitude = 51.5, longitude = 29.9, base = "Bolshoy Bokov", loadoutid = 300}) end
for i = 1, 18 do
  local u = add({type = "Aircraft", name = string.format("RU_IL76_%02d", i), side = "Russia", dbid = 31, latitude = 57.78, longitude = 28.4, base = "Pskov", loadoutid = 310})
  ScenEdit_AssignUnitToMission(u.guid, "BL Airlift")
end
for i = 1, 5 do add({type = "Facility", name = "RU_COL_" .. i, side = "Russia", dbid = 40, latitude = 51.0, longitude = 30.0}) end
local d = 0.012
MOCK.add_rp("Russia", "BL_AF_1", AF_LAT - d, AF_LON - d)
MOCK.add_rp("Russia", "BL_AF_2", AF_LAT - d, AF_LON + d)
MOCK.add_rp("Russia", "BL_AF_3", AF_LAT + d, AF_LON + d)
MOCK.add_rp("Russia", "BL_AF_4", AF_LAT + d, AF_LON - d)
local template_count = MOCK.count_all()

-- ---------------------------------------------------------------- design ---
if design_file and design_file ~= "-" then
  dofile(design_file)
else
  local base = {["air.att.suppression"] = 0.9, ["risk.tolerance"] = 0.5, ["response.strength"] = 400,
                ["response.t_ca"] = 6.5, ["ctx.wave1_t"] = 4.5, ["ctx.wave2_t"] = 26, ["denial.t_fires"] = 40,
                ["denial.fire_intensity"] = 0.8, ["denial.crater_rate"] = 0.1, ["denial.demolish_rate"] = 0.5,
                ["mass.aircraft"] = 20, ["hold.strength"] = 200, ["hold.quality"] = 0.6,
                ["denial.obstacles0"] = 0.3, ["doctrine.clear_rate"] = 0.15, ["ctx.t_relief"] = 24,
                ["air.att.approach_loss"] = 0.03}
  local function with(over)
    local p = {}
    for k, v in pairs(base) do p[k] = v end
    for k, v in pairs(over) do p[k] = v end
    return p
  end
  local names = {}
  for k in pairs(base) do names[#names + 1] = k end
  table.sort(names)
  BL_DESIGN = {scenario = "hostomel_2022", fingerprint = "inline-test", seed = 1, param_names = names,
    runs = {
      {id = 0, seed = 11, p = with({})},
      {id = 1, seed = 22, p = with({["risk.tolerance"] = 0.0, ["response.strength"] = 900})},
      {id = 2, seed = 33, p = with({["mass.aircraft"] = 10, ["hold.strength"] = 100})},
    }}
end

-- ---------------------------------------------------------------- harness --
ScenEdit_RunScript("battlelab/bl_core.lua")
ScenEdit_RunScript("battlelab/bl_hostomel.lua")
BL_HOSTOMEL.cfg.shell_warhead_dbid = 999
BL.cfg.verbose = false

check(BL.selftest(BL_HOSTOMEL), "selftest passes on mock world")
check(BL.start(BL_HOSTOMEL, BL_DESIGN), "batch starts")
check(MOCK.count_all() == 0, "teardown after snapshot leaves an empty world")
check(#BL.template == template_count, "template captured every unit (" .. #BL.template .. ")")

-- ------------------------------------------------------- fake "physics" ----
local spawn_counts, seen_run = {}, {}
local function physics()
  local st = BL.state
  if st.phase ~= "running" then return end
  local ctx, t = st.ctx, st.ctx.elapsed_h
  local s = ctx.state
  if not seen_run[ctx.run.id] then
    seen_run[ctx.run.id] = true
    spawn_counts[ctx.run.id] = {ng = #MOCK.live("UA_NG_"), helo = #MOCK.live("RU_HELO_T_"),
                                ca = #MOCK.live("UA_CA_"), all = MOCK.count_all()}
  end
  if t >= 1.0 and not s._vdv then            -- heliborne troops unload
    s._vdv = true
    for k = 1, math.max(1, #MOCK.live("RU_HELO_T_") // 2) do
      add({type = "Facility", name = "VDV group " .. k, side = "Russia", dbid = 50,
           latitude = AF_LAT + 0.001, longitude = AF_LON - 0.001})
    end
  end
  if t >= 2.0 and not s._ng_gone then         -- garrison out of ammunition
    s._ng_gone = true
    for _, u in ipairs(MOCK.live("UA_NG_")) do MOCK.units[u.guid] = nil end
  end
  local tca = ctx.p["response.t_ca"]
  if t >= tca + 1 and not s._ca_in then       -- counterattack reaches the field
    s._ca_in = true
    for _, u in ipairs(MOCK.live("UA_CA_")) do u.latitude, u.longitude = AF_LAT, AF_LON end
  end
  if t >= tca + 3 and not s._ca_win and ctx.p["response.strength"] >= 700 then
    s._ca_win = true                          -- strong counterattack destroys the VDV
    for _, u in ipairs(MOCK.live("VDV")) do MOCK.units[u.guid] = nil end
  end
  local m = MOCK.missions["BL Airlift"]
  local base = MOCK.units[(function() for g, u in pairs(MOCK.units) do if u.name == "Hostomel Airport" then return g end end end)() or ""]
  if m.isactive and m.activated_at and MOCK.now - m.activated_at >= 2 * 3600
     and base and base.side == "Russia" then
    for _, u in ipairs(MOCK.live("RU_IL76_")) do u.base = "Hostomel Airport" end
  end
end

local guard = 0
local max_ticks = 3000 * (#BL_DESIGN.runs + 1)   -- 48 game hours = 2880 one-minute ticks per run
while BL.state.phase ~= "done" and guard < max_ticks do
  MOCK.now = MOCK.now + 60
  physics()
  BL.tick()
  guard = guard + 1
end
check(BL.state.phase == "done", "batch completes (" .. guard .. " ticks)")
check(MOCK.count_all() == 0, "world empty after the last replication")
check(ScenEdit_GetKeyValue("bl_index") == tostring(#BL_DESIGN.runs + 1) or
      ScenEdit_GetKeyValue("bl_index") == tostring(#BL_DESIGN.runs), "progress index stored")

-- ------------------------------------------------------------- output ------
local lines = {}
if flag == "--no-io" then
  for ln in ScenEdit_GetKeyValue("bl_results"):gmatch("[^\n]+") do lines[#lines + 1] = ln end
  check(BL.out.mode == "keystore", "falls back to KeyStore when io is unavailable")
else
  local f = real_io.open(out_dir .. "/" .. BL.cfg.output_file, "r")
  check(f ~= nil, "results file written")
  for ln in f:lines() do lines[#lines + 1] = ln end
  f:close()
end
local echoed = 0
for _, ln in ipairs(MOCK.printed) do if ln:sub(1, 6) == "BLCSV|" then echoed = echoed + 1 end end
check(#lines == #BL_DESIGN.runs + 1, "header + one row per replication (" .. #lines .. ")")
check(echoed == #BL_DESIGN.runs + 1, "every row echoed to the console with BLCSV|")

local header = {}
for c in lines[1]:gmatch("[^,]+") do header[#header + 1] = c end
local rows = {}
for i = 2, #lines do
  local cells = {}
  for c in (lines[i] .. ","):gmatch("([^,]*),") do cells[#cells + 1] = c end
  check(#cells == #header, ("row %d has %d cells for %d columns"):format(i - 1, #cells, #header))
  local r = {}
  for k, h in ipairs(header) do r[h] = cells[k] end
  rows[tonumber(r.run)] = r
end

if not design_file or design_file == "-" then
  check(rows[0]["m.airbridge"] == "true", "run 0 (permissive) establishes the airbridge")
  check(rows[0]["m.released"] == "true", "run 0 releases the Il-76 wave")
  check(rows[1]["m.airbridge"] == "false" and rows[1]["m.released"] == "false",
        "run 1 (zero risk tolerance) never releases the wave")
  check(rows[1]["m.defender_retakes"] == "true", "run 1 strong counterattack retakes the field")
  check(tonumber(rows[0]["m.t_control"]) and tonumber(rows[0]["m.t_control"]) >= 2.0,
        "control flips only after the garrison leaves (t_control=" .. tostring(rows[0]["m.t_control"]) .. ")")
  check(spawn_counts[2].ng == 5 and spawn_counts[2].helo == 10,
        "run 2 culls garrison to 5 and lift to 10 helicopters")
  check(spawn_counts[0].ca == 0, "counterattack is deferred, not spawned at H-hour")
  check(tonumber(rows[1]["m.counterattack_kept"]) == 6 and tonumber(rows[0]["m.counterattack_kept"]) == 3,
        "counterattack size follows response.strength")
  check(tonumber(rows[1]["m.runway_end"]) < 1.0, "scripted demolition damages the runway after a retake")
end

if failures > 0 then
  real_io.stdout:write(failures .. " FAILURE(S)\n")
  os.exit(1)
end
real_io.stdout:write("ALL LUA HARNESS TESTS PASSED\n")
