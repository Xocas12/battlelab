--[[
A small in-memory stand-in for the CMO Lua API, implementing only the calls
the battlelab harness uses, with the documented signatures. It lets the
replication loop, parameter mapping and output be tested without CMO.
It does NOT simulate combat: tests move/delete units themselves.
]]
MOCK = {now = 1645693200, units = {}, order = {}, next_guid = 1, keystore = {},
        rps = {}, missions = {}, explosions = {}, messages = {}, printed = {},
        lua_dir = ".", ended = false}

local real_print = print
function print(...)
  local parts = {}
  for i = 1, select("#", ...) do parts[#parts + 1] = tostring(select(i, ...)) end
  local line = table.concat(parts, "\t")
  MOCK.printed[#MOCK.printed + 1] = line
  if MOCK.echo then real_print(line) end
end

local function guid()
  MOCK.next_guid = MOCK.next_guid + 1
  return string.format("mock-%06d", MOCK.next_guid)
end

local function find(sel)
  if type(sel) == "string" then
    if MOCK.units[sel] then return MOCK.units[sel] end
    for _, g in ipairs(MOCK.order) do
      local u = MOCK.units[g]
      if u and u.name == sel then return u end
    end
    return nil
  end
  if sel.guid then return MOCK.units[sel.guid] end
  local name = sel.name or sel.unitname
  for _, g in ipairs(MOCK.order) do
    local u = MOCK.units[g]
    if u and u.name == name and (sel.side == nil or u.side == sel.side) then return u end
  end
  return nil
end

function MOCK.wrap(u)
  return {guid = u.guid, name = u.name, side = u.side, type = u.type, dbid = u.dbid,
          latitude = u.latitude, longitude = u.longitude, altitude = u.altitude,
          heading = u.heading, proficiency = u.proficiency, group = u.group,
          loadoutdbid = u.loadoutid,
          base = u.base and {name = u.base} or nil,
          mission = u.mission and {name = u.mission} or nil,
          damage = {dp = u.dp, startdp = u.startdp}}
end

function ScenEdit_AddUnit(d)
  assert(d.type and d.side and d.dbid and d.name, "AddUnit: type/side/dbid/name required")
  if d.base then assert(find(d.base), "AddUnit: unknown base " .. d.base) end
  local b = d.base and find(d.base)
  local u = {guid = guid(), name = d.name, side = d.side, type = d.type, dbid = d.dbid,
             latitude = d.latitude or d.lat or (b and b.latitude),
             longitude = d.longitude or d.lon or (b and b.longitude),
             altitude = d.altitude or 0, heading = d.heading or 0,
             proficiency = d.proficiency or "Regular", base = d.base, loadoutid = d.loadoutid,
             group = d.group, dp = 100, startdp = 100}
  MOCK.units[u.guid] = u
  MOCK.order[#MOCK.order + 1] = u.guid
  return MOCK.wrap(u)
end

function ScenEdit_GetUnit(sel)
  local u = find(sel)
  if not u then error("unit not found") end
  return MOCK.wrap(u)
end

function ScenEdit_DeleteUnit(sel)
  local u = find(sel)
  if not u then error("unit not found") end
  MOCK.units[u.guid] = nil
  return true
end

function ScenEdit_SetUnit(t)
  local u = find(t)
  if not u then error("unit not found") end
  if t.course then u.course = t.course end
  if t.latitude then u.latitude = t.latitude end
  if t.longitude then u.longitude = t.longitude end
  return MOCK.wrap(u)
end

function ScenEdit_SetUnitSide(t)
  local n = 0
  for _, g in ipairs(MOCK.order) do
    local u = MOCK.units[g]
    if u and u.side == t.side and (u.name == t.name or u.group == t.name) then
      u.side = t.newside
      n = n + 1
    end
  end
  if n == 0 then error("SetUnitSide: nothing matched") end
  return true
end

function VP_GetSides()
  return {{name = "Russia", guid = "side-ru"}, {name = "Ukraine", guid = "side-ua"}}
end

function VP_GetSide(sel)
  local out = {}
  for _, g in ipairs(MOCK.order) do
    local u = MOCK.units[g]
    if u and u.side == (sel.side or sel.name) then out[#out + 1] = {guid = u.guid, name = u.name} end
  end
  return {name = sel.side or sel.name, units = out}
end

function ScenEdit_GetReferencePoints(sel)
  local out = {}
  for _, n in ipairs(sel.area) do
    local rp = MOCK.rps[n]
    if rp and rp.side == sel.side then out[#out + 1] = {name = n, latitude = rp.lat, longitude = rp.lon} end
  end
  return out
end

function ScenEdit_CurrentTime() return MOCK.now end
function ScenEdit_SetKeyValue(k, v) MOCK.keystore[k] = v end
function ScenEdit_GetKeyValue(k) return MOCK.keystore[k] or "" end

function ScenEdit_AssignUnitToMission(u, m)
  local unit = find(u)
  if not unit or not MOCK.missions[m] then error("assign failed") end
  unit.mission = m
  return true
end

function ScenEdit_GetMission(side, name)
  local m = MOCK.missions[name]
  if not m then error("no mission") end
  return m
end

function ScenEdit_SetMission(side, name, opts)
  local m = MOCK.missions[name]
  if not m then error("no mission") end
  if opts.isactive ~= nil then
    if opts.isactive and not m.isactive then m.activated_at = MOCK.now end
    m.isactive = opts.isactive
  end
  return m
end

function ScenEdit_AddExplosion(t)
  assert(t.warheadid and t.lat and t.lon, "AddExplosion: warheadid/lat/lon required")
  MOCK.explosions[#MOCK.explosions + 1] = t
  for _, g in ipairs(MOCK.order) do
    local u = MOCK.units[g]
    if u and u.name:sub(1, 6) == "BL_RWY" and math.abs(u.latitude - t.lat) < 0.001 then
      u.dp = math.max(0, u.dp - 8)
    end
  end
  return true
end

function Tool_Range(a, b)
  local function pos(x)
    if type(x) == "table" then return x.latitude, x.longitude end
    local u = MOCK.units[x]
    return u.latitude, u.longitude
  end
  local la1, lo1 = pos(a)
  local la2, lo2 = pos(b)
  local dlat, dlon = (la2 - la1) * 60, (lo2 - lo1) * 60 * math.cos(math.rad(la1))
  return math.sqrt(dlat * dlat + dlon * dlon)
end

function ScenEdit_SpecialMessage(side, msg) MOCK.messages[#MOCK.messages + 1] = msg; return 1 end
function ScenEdit_EndScenario() MOCK.ended = true end
function GetBuildNumber() return "mock-1.0" end
function Tool_EmulateNoConsole() return true end
function ScenEdit_RunScript(path) dofile(MOCK.lua_dir .. "/" .. path) end

-- scenario construction (used by bl_build_hostomel.lua) --------------------------
MOCK.events, MOCK.triggers, MOCK.actions, MOCK.postures = {}, {}, {}, {}
function ScenEdit_AddSide(t) assert(t.side, "AddSide: side required"); return true end
function ScenEdit_SetSidePosture(a, b, p) MOCK.postures[a .. ">" .. b] = p; return true end
function ScenEdit_AddReferencePoint(t)
  assert(t.side and t.name and t.lat and t.lon, "AddReferencePoint: side/name/lat/lon required")
  MOCK.rps[t.name] = {side = t.side, lat = t.lat, lon = t.lon}
  return {name = t.name}
end
function ScenEdit_AddMission(side, name, mtype, opts)
  assert(side and name and mtype, "AddMission: side/name/type required")
  MOCK.missions[name] = {name = name, side = side, type = mtype, isactive = true, opts = opts}
  return MOCK.missions[name]
end
function ScenEdit_SetEvent(name, t) MOCK.events[name] = {opts = t, triggers = {}, actions = {}}; return true end
function ScenEdit_SetTrigger(t) assert(t.name and t.type); MOCK.triggers[t.name] = t; return true end
function ScenEdit_SetAction(t) assert(t.name and t.type); MOCK.actions[t.name] = t; return true end
function ScenEdit_SetEventTrigger(ev, t)
  assert(MOCK.events[ev] and MOCK.triggers[t.name], "SetEventTrigger: unknown event/trigger")
  table.insert(MOCK.events[ev].triggers, t.name); return true
end
function ScenEdit_SetEventAction(ev, t)
  assert(MOCK.events[ev] and MOCK.actions[t.name], "SetEventAction: unknown event/action")
  table.insert(MOCK.events[ev].actions, t.name); return true
end
function ScenEdit_SetTime(t) MOCK.time = t; return true end

-- helpers for tests ----------------------------------------------------------
function MOCK.add_rp(side, name, lat, lon) MOCK.rps[name] = {side = side, lat = lat, lon = lon} end
function MOCK.add_mission(side, name) MOCK.missions[name] = {name = name, side = side, isactive = true} end
function MOCK.live(prefix)
  local out = {}
  for _, g in ipairs(MOCK.order) do
    local u = MOCK.units[g]
    if u and u.name:sub(1, #prefix) == prefix then out[#out + 1] = u end
  end
  return out
end
function MOCK.count_all()
  local n = 0
  for _ in pairs(MOCK.units) do n = n + 1 end
  return n
end
