--[[
battlelab CMO probe: checks, in a live build, every assumption the harness
makes about the Lua API, without building the Hostomel scenario and without
running the clock.

Open ANY scenario that has at least one airbase with aircraft on it and a
ground unit (a stock scenario is fine), open the Lua console and run:

    ScenEdit_RunScript('battlelab/bl_probe.lua')

It only reads, unless you set BL_PROBE_WRITE = true before running it; then it
also spawns ONE copy of a ground unit, tests ScenEdit_SetUnit{course=...} and
ScenEdit_SetUnitSide on it, and deletes it again (do this on an unsaved copy).

Copy every line starting with BLPROBE| from the console into a text file and
send it back; `battlelab` does not read it, a human (or Claude) does.
Plain Lua 5.3, public-edition functions only, every call wrapped in pcall.
]]

local out = {}
local function say(key, value)
  local line = ("BLPROBE|%s|%s"):format(key, tostring(value))
  out[#out + 1] = line
  print(line)
end

local function try(f, ...)
  local ok, v = pcall(f, ...)
  if ok then return v end
  return "ERROR: " .. tostring(v)
end

local function describe(v, depth)
  depth = depth or 0
  local t = type(v)
  if t ~= "table" and t ~= "userdata" then return t .. ":" .. tostring(v) end
  if depth > 0 then return t end
  local keys = {}
  local ok = pcall(function() for k, _ in pairs(v) do keys[#keys + 1] = tostring(k) end end)
  if not ok or #keys == 0 then return t .. "(not iterable)" end
  table.sort(keys)
  if #keys > 25 then keys = {table.unpack(keys, 1, 25)}; keys[26] = "..." end
  return t .. "{" .. table.concat(keys, ",") .. "}"
end

local function field(u, name)
  local ok, v = pcall(function() return u[name] end)
  if not ok then return "ERROR: " .. tostring(v) end
  return describe(v)
end

local function sub(u, name, key)
  local ok, v = pcall(function() local x = u[name]; return x and x[key] end)
  if not ok then return "ERROR: " .. tostring(v) end
  return describe(v, 1)
end

-- 1. environment ------------------------------------------------------------
say("build", try(function() return GetBuildNumber() end))
say("lua_version", _VERSION)
say("io_available", io ~= nil and io.open ~= nil)
say("scenariofolder", rawget(_G, "_scenariofolder_") or "nil")
local api = {
  "ScenEdit_AddUnit", "ScenEdit_DeleteUnit", "ScenEdit_GetUnit", "ScenEdit_SetUnit",
  "ScenEdit_SetUnitSide", "ScenEdit_AssignUnitToMission", "ScenEdit_GetMission",
  "ScenEdit_SetMission", "ScenEdit_GetReferencePoints", "ScenEdit_CurrentTime",
  "ScenEdit_SetKeyValue", "ScenEdit_GetKeyValue", "ScenEdit_AddExplosion",
  "ScenEdit_RunScript", "ScenEdit_SpecialMessage", "ScenEdit_EndScenario",
  "VP_GetSides", "VP_GetSide", "Tool_Range", "Tool_EmulateNoConsole", "GetBuildNumber",
}
for _, fn in ipairs(api) do say("api." .. fn, type(rawget(_G, fn)) == "function") end
say("current_time", try(function() return ScenEdit_CurrentTime() end))
local fpath = (rawget(_G, "_scenariofolder_") or ".") .. "/battlelab_probe.tmp"
say("file_write", try(function()
  local f = io.open(fpath, "w"); if not f then return false end
  f:write("ok"); f:close(); return true
end))

-- 2. find one unit of each kind -------------------------------------------------
local picked = {}
local counts = {}
local sides = try(function() return VP_GetSides() end)
if type(sides) ~= "table" then say("sides", sides) sides = {} end
for _, s in ipairs(sides) do
  local side = try(function() return VP_GetSide({side = s.name}) end)
  say("side", tostring(s.name) .. " units=" .. tostring(type(side) == "table" and side.units
      and #side.units or "?"))
  for _, ref in ipairs(type(side) == "table" and side.units or {}) do
    local u = try(function() return ScenEdit_GetUnit({guid = ref.guid}) end)
    if type(u) ~= "string" and u then
      local kind = tostring(u.type)
      counts[kind] = (counts[kind] or 0) + 1
      local based = pcall(function() return u.base.name end) and u.base ~= nil
      local slot = kind
      if kind == "Aircraft" and based then slot = "Aircraft(based)" end
      if kind == "Facility" and pcall(function() return u.damage.dp end) then
        slot = picked["Facility"] and "Facility2" or "Facility"
      end
      picked[slot] = picked[slot] or u
    end
  end
end
for k, n in pairs(counts) do say("count." .. k, n) end

-- 3. the fields the harness reads ----------------------------------------------
local FIELDS = {"name", "guid", "side", "type", "dbid", "latitude", "longitude", "altitude",
                "heading", "speed", "proficiency", "base", "damage", "loadoutdbid", "loadoutid",
                "loadout", "mission", "group", "course", "condition", "fuel", "airbornetime"}
for slot, u in pairs(picked) do
  local p = "unit[" .. slot .. "]"
  say(p .. ".name", try(function() return u.name end))
  for _, f in ipairs(FIELDS) do say(p .. "." .. f, field(u, f)) end
  say(p .. ".base.name", sub(u, "base", "name"))
  say(p .. ".mission.name", sub(u, "mission", "name"))
  say(p .. ".group.name", sub(u, "group", "name"))
  for _, k in ipairs({"dp", "startdp", "dp_percent", "flood", "fires"}) do
    say(p .. ".damage." .. k, sub(u, "damage", k))
  end
end

-- 4. optional write test on a throwaway copy ----------------------------------------
if rawget(_G, "BL_PROBE_WRITE") then
  local src = picked["Facility"] or picked["Facility2"]
  if not src then
    say("write_test", "skipped: no facility/ground unit found")
  else
    local ok, u = pcall(ScenEdit_AddUnit, {type = src.type, name = "BLPROBE_TMP", side = src.side,
      dbid = tonumber(src.dbid), latitude = tonumber(src.latitude) + 0.01,
      longitude = tonumber(src.longitude) + 0.01})
    say("write.add_unit", ok and u and "ok" or ("ERROR: " .. tostring(u)))
    if ok and u then
      local lat, lon = tonumber(src.latitude) + 0.05, tonumber(src.longitude) + 0.05
      say("write.set_course", try(function()
        ScenEdit_SetUnit({guid = u.guid, course = {{latitude = lat, longitude = lon}}})
        return describe(ScenEdit_GetUnit({guid = u.guid}).course)
      end))
      local other
      for _, s in ipairs(sides) do if s.name ~= src.side then other = s.name break end end
      if other then
        say("write.set_side", try(function()
          ScenEdit_SetUnitSide({side = src.side, name = "BLPROBE_TMP", newside = other})
          return ScenEdit_GetUnit({guid = u.guid}).side
        end))
      end
      say("write.explosion", try(function()
        ScenEdit_AddExplosion({warheadid = 0, lat = lat, lon = lon, altitude = 0})
        return "called (warheadid 0; real runs need cfg.shell_warhead_dbid)"
      end))
      say("write.delete", try(function() ScenEdit_DeleteUnit({guid = u.guid}); return "ok" end))
    end
  end
else
  say("write_test", "skipped (set BL_PROBE_WRITE = true to run it on an unsaved copy)")
end

say("done", #out + 1 .. " lines")
return out
