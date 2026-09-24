--[[
Builds the battlelab Hostomel scenario from an empty one, so nothing has to be
placed by hand in the editor.

  1. Fill in cmo/lua/battlelab/bl_build_db.lua (DBIDs for your database).
  2. In CMO: File > New scenario (any database that has the units you chose),
     open the Lua console and run
         ScenEdit_RunScript('battlelab/bl_build_hostomel.lua')
  3. Read the BLBUILD| lines. Anything marked FAIL can be done by hand in the
     editor; the line says what. Then File > Save As (this is the pristine
     template every batch starts from).

Safe to re-run: units, points, missions and events that already exist (by
name) are skipped. Plain Lua 5.3; public-edition functions only; every CMO
call is wrapped in pcall and reported.

Geography: Hostomel (Antonov) airport, 24 Feb 2022. Helicopters start at a
forward base in southern Belarus, the Il-76s at Pskov; the Ukrainian
counterattack forms up near Bucha, artillery further south. Positions are
approximate; the harness only needs the airfield polygon to be right.
]]

local B = {}
BL_BUILDER = B
B.lines, B.fails = {}, 0

local function say(status, what, detail)
  if status == "FAIL" then B.fails = B.fails + 1 end
  local line = ("BLBUILD|%s|%s|%s"):format(status, what, detail or "")
  B.lines[#B.lines + 1] = line
  print(line)
end

local function call(what, f, ...)
  local ok, res = pcall(f, ...)
  if ok and res ~= false then say("OK", what) return true, res end
  say("FAIL", what, tostring(res))
  return false, res
end

if not BL_BUILD_DB then pcall(ScenEdit_RunScript, 'battlelab/bl_build_db.lua') end
local DB = BL_BUILD_DB or {}

-- ---------------------------------------------------------------------------
-- Layout
-- ---------------------------------------------------------------------------
local RU, UA = "Russia", "Ukraine"
local AF = {lat = 50.6035, lon = 30.1919}                -- Hostomel airport centre
local L = {
  airbase = {name = "Hostomel Airport", lat = AF.lat, lon = AF.lon},
  ru_fob = {name = "Belarus FOB", lat = 51.45, lon = 29.95},
  pskov = {name = "Pskov", lat = 57.785, lon = 28.395},
  -- runway 15/33, about 3.5 km, NW -> SE
  runway = {{50.6160, 30.1790}, {50.6085, 30.1870}, {50.6010, 30.1950}, {50.5935, 30.2030}},
  poly = {{50.6250, 30.1650}, {50.6250, 30.2200}, {50.5820, 30.2200}, {50.5820, 30.1650}},
  garrison = {{50.6120, 30.1780}, {50.6070, 30.1830}, {50.6040, 30.1990}, {50.5990, 30.1880},
              {50.5960, 30.2010}, {50.6100, 30.1960}, {50.6020, 30.1760}, {50.5900, 30.1950}},
  counterattack = {50.545, 30.215},                         -- Bucha
  sam = {{50.660, 30.250}, {50.560, 30.120}, {50.640, 30.100}},
  artillery = {{50.480, 30.250}, {50.500, 30.100}},
  column = {50.950, 29.950},                                -- from Belarus, north-west
}
local N = {helo = 20, il76 = 18, garrison = 8, counterattack = 6, vdv = 20, column = 5}

-- ---------------------------------------------------------------------------
-- 0. check the database IDs before touching the scenario
-- ---------------------------------------------------------------------------
local need = {"airfield", "ua_infantry", "ru_infantry", "ru_mech", "mi8", "il76"}
local missing = {}
for _, k in ipairs(need) do if not DB[k] then missing[#missing + 1] = k end end
if #missing > 0 then
  say("FAIL", "database IDs", "fill in bl_build_db.lua first: " .. table.concat(missing, ", "))
  say("STOP", "nothing was changed")
  return B
end

-- ---------------------------------------------------------------------------
-- helpers
-- ---------------------------------------------------------------------------
local function exists(name, side)
  return pcall(function()
    local u = ScenEdit_GetUnit({side = side, name = name})
    assert(u ~= nil)
  end)
end

local function add_facility(side, name, dbid, lat, lon)
  if exists(name, side) then say("SKIP", name, "exists") return end
  if not dbid then say("FAIL", name, "no DBID") return end
  call("unit " .. name, ScenEdit_AddUnit, {type = "Facility", side = side, name = name,
       dbid = dbid, latitude = lat, longitude = lon})
end

local function add_aircraft(side, name, dbid, loadout, base)
  if exists(name, side) then say("SKIP", name, "exists") return end
  local d = {type = "Aircraft", side = side, name = name, dbid = dbid, base = base}
  if loadout then d.loadoutid = loadout end
  call("aircraft " .. name, ScenEdit_AddUnit, d)
end

-- ---------------------------------------------------------------------------
-- 1. sides and postures
-- ---------------------------------------------------------------------------
local have = {}
pcall(function() for _, s in ipairs(VP_GetSides()) do have[s.name] = true end end)
for _, s in ipairs({RU, UA}) do
  if have[s] then say("SKIP", "side " .. s, "exists")
  else call("side " .. s, ScenEdit_AddSide, {side = s}) end
end
call("posture Russia->Ukraine hostile", ScenEdit_SetSidePosture, RU, UA, "H")
call("posture Ukraine->Russia hostile", ScenEdit_SetSidePosture, UA, RU, "H")

-- ---------------------------------------------------------------------------
-- 2. airfields
-- ---------------------------------------------------------------------------
add_facility(UA, L.airbase.name, DB.airfield, L.airbase.lat, L.airbase.lon)
add_facility(RU, L.ru_fob.name, DB.airfield, L.ru_fob.lat, L.ru_fob.lon)
add_facility(RU, L.pskov.name, DB.airfield, L.pskov.lat, L.pskov.lon)
for i, p in ipairs(L.runway) do
  add_facility(UA, "BL_RWY_" .. i, DB.runway_segment or DB.airfield, p[1], p[2])
end

-- ---------------------------------------------------------------------------
-- 3. airfield polygon (attacker-side reference points)
-- ---------------------------------------------------------------------------
for i, p in ipairs(L.poly) do
  local name = "BL_AF_" .. i
  local ok = pcall(function()
    local rp = ScenEdit_GetReferencePoints({side = RU, area = {name}})
    assert(rp and #rp > 0)
  end)
  if ok then say("SKIP", name, "exists")
  else call("reference point " .. name, ScenEdit_AddReferencePoint,
            {side = RU, name = name, lat = p[1], lon = p[2]}) end
end

-- ---------------------------------------------------------------------------
-- 4. ground forces
-- ---------------------------------------------------------------------------
for i = 1, N.garrison do
  local p = L.garrison[(i - 1) % #L.garrison + 1]
  add_facility(UA, ("UA_NG_%02d"):format(i), DB.ua_infantry, p[1], p[2])
end
for i = 1, N.counterattack do
  add_facility(UA, ("UA_CA_%02d"):format(i), DB.ua_infantry,
               L.counterattack[1] + 0.003 * (i % 3), L.counterattack[2] + 0.004 * (i // 3))
end
for i, p in ipairs(L.sam) do add_facility(UA, "UA_SAM_" .. i, DB.ua_sam, p[1], p[2]) end
for i, p in ipairs(L.artillery) do add_facility(UA, "UA_ART_" .. i, DB.ua_artillery, p[1], p[2]) end
-- VDV squads are templates only: the plugin spawns each at the airfield when its helicopter
-- arrives. Park them at the helicopter base, well away from any fighting.
for i = 1, N.vdv do
  add_facility(RU, ("RU_VDV_%02d"):format(i), DB.ru_infantry,
               L.ru_fob.lat + 0.002 * (i % 5), L.ru_fob.lon + 0.003 * (i // 5))
end
for i = 1, N.column do
  add_facility(RU, "RU_COL_" .. i, DB.ru_mech, L.column[1] + 0.003 * i, L.column[2])
end

-- ---------------------------------------------------------------------------
-- 5. missions (before the aircraft so they can be assigned)
-- ---------------------------------------------------------------------------
local function mission(side, name, mtype, opts)
  local ok = pcall(function() assert(ScenEdit_GetMission(side, name)) end)
  if ok then say("SKIP", "mission " .. name, "exists") return end
  call("mission " .. name, ScenEdit_AddMission, side, name, mtype, opts)
end
mission(RU, "BL Assault", "Support", {zone = {"BL_AF_1", "BL_AF_2", "BL_AF_3", "BL_AF_4"}})
mission(RU, "BL Airlift", "Ferry", {destination = L.airbase.name})
call("BL Airlift starts inactive", ScenEdit_SetMission, RU, "BL Airlift", {isactive = false})

-- ---------------------------------------------------------------------------
-- 6. aircraft
-- ---------------------------------------------------------------------------
for i = 1, N.helo do
  local name = ("RU_HELO_T_%02d"):format(i)
  add_aircraft(RU, name, DB.mi8, DB.mi8_loadout, L.ru_fob.name)
  pcall(ScenEdit_AssignUnitToMission, name, "BL Assault")
end
for i = 1, N.il76 do
  local name = ("RU_IL76_%02d"):format(i)
  add_aircraft(RU, name, DB.il76, DB.il76_loadout, L.pskov.name)
  pcall(ScenEdit_AssignUnitToMission, name, "BL Airlift")
end

-- ---------------------------------------------------------------------------
-- 7. the two events that drive the harness
-- ---------------------------------------------------------------------------
local function event(name, trigger, action)
  call("event " .. name, ScenEdit_SetEvent, name, {mode = "add", IsRepeatable = trigger.repeatable,
       IsActive = true})
  call("trigger " .. trigger.name, ScenEdit_SetTrigger, trigger.spec)
  call("action " .. action.name, ScenEdit_SetAction, {mode = "add", type = "LuaScript",
       name = action.name, ScriptText = action.script})
  call("link trigger -> " .. name, ScenEdit_SetEventTrigger, name,
       {mode = "add", name = trigger.name})
  call("link action -> " .. name, ScenEdit_SetEventAction, name,
       {mode = "add", name = action.name})
end
event("BL Init",
      {name = "BL scenario loaded", repeatable = false,
       spec = {mode = "add", type = "ScenLoaded", name = "BL scenario loaded"}},
      {name = "BL run harness", script = "ScenEdit_RunScript('battlelab/bl_run.lua')"})
event("BL Tick",
      {name = "BL every minute", repeatable = true,
       spec = {mode = "add", type = "RegularTime", name = "BL every minute", interval = 1}},
      {name = "BL tick", script = "BL.tick()"})

-- ---------------------------------------------------------------------------
-- 8. clock: 24 Feb 2022, assault lift-off ~08:20 UTC (10:20 local)
-- ---------------------------------------------------------------------------
call("scenario start time", ScenEdit_SetTime,
     {Date = "2/24/2022", Time = "08:20:00", StartDate = "2/24/2022", StartTime = "08:20:00"})

if B.fails == 0 then
  say("DONE", "all steps OK", "save the scenario (File > Save As) and run BL.selftest(BL_HOSTOMEL)")
else
  say("DONE", B.fails .. " step(s) failed",
      "fix those in the editor (each FAIL line says what), then save and run the selftest")
end
return B
