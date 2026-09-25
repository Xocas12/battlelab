--[[
battlelab CMO plugin - Hostomel 2022
====================================
Division of labour
  CMO simulates what it models well: helicopter ingress against Ukrainian air
  defence, MANPADS/AAA engagements, air-to-air, weapons and sensors.
  This plugin adds what CMO does not model: who controls the airfield, the
  runway being blocked/cratered, the go/no-go rule for the Il-76 wave, and
  the timing of Ukrainian reinforcements and fires - all driven by the SAME
  parameter names as scenarios/hostomel_2022.yaml.

Naming conventions (set these names in the scenario editor)
  RU_HELO_T_*   transport helicopters (Mi-8) carrying the assault force
  RU_HELO_A_*   attack helicopters (Ka-52 / Mi-24)
  RU_IL76_*     the Il-76 wave, assigned to mission cfg.airlift_mission
  RU_COL_*      Russian ground column (spawned at ctx.t_relief)
  UA_NG_*       National Guard garrison at the airfield
  UA_CA_*       Ukrainian counterattack force (spawned at response.t_ca)
  UA_ART_*      Ukrainian artillery (optional; fires stop if all are lost)
  UA_SAM_*      Ukrainian air defence that SEAD may have suppressed
  BL_RWY_*      runway segment facilities of the airbase
  BL_AF_1..n    reference points (attacker side) outlining the airfield
]]

BL_HOSTOMEL = {scenario = "hostomel_2022"}
local P = BL_HOSTOMEL

P.cfg = {
  attacker = "Russia",
  defender = "Ukraine",
  airfield_rps = {"BL_AF_1", "BL_AF_2", "BL_AF_3", "BL_AF_4"},
  airbase_name = "Hostomel Airport",       -- defender airbase unit/group
  airlift_mission = "BL Airlift",           -- attacker mission for the Il-76s
  static_prefixes = {"BL_RWY"},             -- facilities that never count as troops
  garrison_nominal = 200,                   -- hold.strength that keeps every UA_NG_ unit
  counterattack_nominal = 900,              -- response.strength that keeps every UA_CA_
  control_hold_minutes = 15,                -- sole occupation needed to flip control
  il76_flight_h = 2.0,                      -- Pskov -> Hostomel
  loiter_h = 1.5,
  r_min = 0.6,                              -- usable runway needed to land
  troops_per_aircraft = 55,
  airbridge_troops = 500,
  threat_radius_nm = 10,
  sam_risk = 0.01,                          -- added p(loss) per live SAM within radius
  fire_risk = 0.25,                         -- as in the native model
  runway_risk = 0.10,
  shell_warhead_dbid = nil,                 -- REQUIRED for scripted fires: an HE
                                            -- artillery warhead DBID from your DB
  max_shells_per_hour = 24,                 -- at fire_intensity = 1
  max_demolitions_per_hour = 12,            -- at demolish_rate = 1
  delivery_radius_nm = 1.5,                 -- a transport helicopter this close to the
                                            -- airfield centre unloads its RU_VDV_ squad(s)
}

P.metric_fields = {
  "landed", "airbridge", "t_airbridge", "t_first_landing", "transports_lost",
  "t_control", "attacker_ever_controls", "attacker_lost_control", "attacker_holds_end",
  "defender_retakes", "runway_end", "released", "t_release", "helos_lost",
  "sams_kept", "garrison_kept", "counterattack_kept", "vdv_delivered",
}

local function pv(ctx, name, fallback)
  local v = ctx.p[name]
  if v == nil then return fallback end
  return v
end

local function starts(s, list)
  for _, pre in ipairs(list) do if BL.starts_with(s, pre) then return true end end
  return false
end

local function proficiency(q)
  if q < 0.6 then return "Novice" elseif q < 0.8 then return "Cadet"
  elseif q < 1.0 then return "Regular" elseif q < 1.2 then return "Veteran" end
  return "Ace"
end

-- ---------------------------------------------------------------------------
-- Batch start: index template units by role
-- ---------------------------------------------------------------------------
function P.on_batch_start(template)
  P.roles = {}
  for _, r in ipairs(template) do
    for _, pre in ipairs({"RU_HELO_T_", "UA_NG_", "UA_CA_", "UA_SAM_", "RU_IL76_", "BL_RWY",
                          "RU_VDV_"}) do
      if BL.starts_with(r.name, pre) then
        P.roles[pre] = P.roles[pre] or {}
        table.insert(P.roles[pre], r.name)
      end
    end
  end
  P.vdv_tpl = {}
  for _, r in ipairs(template) do
    if BL.starts_with(r.name, "RU_VDV_") then P.vdv_tpl[r.name] = r end
  end
  for _, list in pairs(P.roles) do table.sort(list) end
  P.rank = {}
  for _, list in pairs(P.roles) do
    for i, n in ipairs(list) do P.rank[n] = i end
  end
  P.poly = BL.polygon(P.cfg.attacker, P.cfg.airfield_rps)
  P.center_lat, P.center_lon = BL.centroid(P.poly)
end

local function count(pre) return P.roles[pre] and #P.roles[pre] or 0 end

-- ---------------------------------------------------------------------------
-- Parameter -> unit mapping (called for every template unit, every run)
-- Return the record to spawn now, nil to omit, or (record, hours) to defer.
-- ---------------------------------------------------------------------------
function P.mutate(rec, ctx)
  local r = {}
  for k, v in pairs(rec) do r[k] = v end
  local n = r.name
  local s = ctx.state
  s.kept = s.kept or {sam = 0, ng = 0, ca = 0}

  if BL.starts_with(n, "RU_VDV_") then                     -- delivered by helicopter, below
    return nil
  end

  if BL.starts_with(n, "UA_SAM_") then                     -- AIR: SEAD survivors
    if ctx.rng:bernoulli(pv(ctx, "air.att.suppression", 0)) then return nil end
    s.kept.sam = s.kept.sam + 1
    return r
  elseif BL.starts_with(n, "RU_HELO_T_") then              -- MASS: lift size
    local keep = math.floor(pv(ctx, "mass.aircraft", count("RU_HELO_T_")) + 0.5)
    if P.rank[n] > keep then return nil end
    return r
  elseif BL.starts_with(n, "UA_NG_") then                  -- HOLD: garrison size/quality
    local frac = math.min(1, pv(ctx, "hold.strength", P.cfg.garrison_nominal) / P.cfg.garrison_nominal)
    if P.rank[n] > math.ceil(frac * count("UA_NG_")) then return nil end
    r.proficiency = proficiency(pv(ctx, "hold.quality", 1.0))
    s.kept.ng = s.kept.ng + 1
    return r
  elseif BL.starts_with(n, "UA_CA_") then                  -- RESPONSE: size and timing
    local frac = math.min(1, pv(ctx, "response.strength", P.cfg.counterattack_nominal)
                            / P.cfg.counterattack_nominal)
    if P.rank[n] > math.ceil(frac * count("UA_CA_")) then return nil end
    s.kept.ca = s.kept.ca + 1
    return r, pv(ctx, "response.t_ca", 6.5)
  elseif BL.starts_with(n, "UA_ART_") then                 -- DENIAL: fires timing
    return r, pv(ctx, "denial.t_fires", 5.0)
  elseif BL.starts_with(n, "RU_COL_") then                 -- context: ground link-up
    return r, pv(ctx, "ctx.t_relief", 24.0)
  end
  return r
end

function P.on_spawned(ctx, rec, u)
  if BL.starts_with(rec.name, "UA_CA_") or BL.starts_with(rec.name, "RU_COL_") then
    pcall(ScenEdit_SetUnit, {guid = u.guid,
          course = {{latitude = P.center_lat, longitude = P.center_lon}}})
  end
end

-- ---------------------------------------------------------------------------
-- Run start
-- ---------------------------------------------------------------------------
local function set_airlift(active)
  pcall(ScenEdit_SetMission, P.cfg.attacker, P.cfg.airlift_mission, {isactive = active})
end

function P.on_run_start(ctx)
  set_airlift(false)
  local s = ctx.state
  s.control, s.candidate, s.candidate_since = "defender", nil, nil
  s.t_control, s.lost_after, s.retakes = nil, false, false
  s.landed_at, s.landed_list, s.lost_il76 = {}, {}, {}
  s.first_landing, s.t_airbridge = nil, nil
  s.released, s.t_release = false, nil
  s.obstructed_until = nil
  s.shell_debt = 0
  s.delivered_helo, s.vdv_next, s.vdv_delivered = {}, 1, 0
end

-- ---------------------------------------------------------------------------
-- Heliborne insertion. CMO respawns the helicopters without cargo, so the
-- troops are scripted: each RU_HELO_T_ that gets within delivery_radius_nm of
-- the airfield unloads its share of the RU_VDV_ template squads there, each
-- surviving the landing with probability 1 - mass.dz_loss. Helicopters shot
-- down on the way (by CMO's own air defence) deliver nothing, which is the
-- ingress loss. Without RU_VDV_ units in the scenario nothing is scripted.
-- ---------------------------------------------------------------------------
local function deliver_vdv(ctx)
  local s = ctx.state
  local squads = P.roles["RU_VDV_"] or {}
  local helos = P.roles["RU_HELO_T_"] or {}
  if #squads == 0 or #helos == 0 then return end
  local per_helo = math.max(1, math.floor(#squads / #helos + 0.5))
  for _, hname in ipairs(helos) do
    local g = ctx.spawned[hname]
    if g and not s.delivered_helo[hname] then
      local u = BL.get(g)
      local ok, d = pcall(Tool_Range, {latitude = P.center_lat, longitude = P.center_lon}, g)
      if u and ok and tonumber(d) and tonumber(d) <= P.cfg.delivery_radius_nm then
        s.delivered_helo[hname] = true
        for _ = 1, per_helo do
          local sq = squads[s.vdv_next]
          if not sq then break end
          s.vdv_next = s.vdv_next + 1
          if not ctx.rng:bernoulli(pv(ctx, "mass.dz_loss", 0)) then
            local r = {}
            for k, v in pairs(P.vdv_tpl[sq]) do r[k] = v end
            r.latitude = tonumber(u.latitude) + ctx.rng:range(-0.002, 0.002)
            r.longitude = tonumber(u.longitude) + ctx.rng:range(-0.003, 0.003)
            r.altitude, r.base, r.mission = nil, nil, nil
            BL.spawn_record(ctx, r)
            s.vdv_delivered = s.vdv_delivered + 1
          end
        end
        pcall(ScenEdit_SetUnit, {guid = g, RTB = true})
      end
    end
  end
end

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------
local function alive(ctx, name)
  local g = ctx.spawned[name]
  return g and BL.get(g) or nil
end

local function inside(u)
  return u and BL.point_in_poly(tonumber(u.latitude), tonumber(u.longitude), P.poly)
end

local function health(u)
  if not u then return 0 end
  local ok, v = pcall(function()
    local d = u.damage
    if d and d.dp_percent then return 1 - tonumber(d.dp_percent) / 100 end
    if d and d.dp and d.startdp and tonumber(d.startdp) > 0 then
      return tonumber(d.dp) / tonumber(d.startdp)
    end
    return nil
  end)
  if ok and v then return math.max(0, math.min(1, v)) end
  return 1
end

function P.runway_usable(ctx)
  local segs = P.roles["BL_RWY"] or {}
  if #segs == 0 then return 1 end
  local total = 0
  for _, n in ipairs(segs) do total = total + health(alive(ctx, n)) end
  return total / #segs
end

local function group_name(u)
  local ok, g = pcall(function()
    if type(u.group) == "table" then return u.group.name end
    return u.group
  end)
  return ok and g or nil
end

-- Airbase structures flip sides with the base; they are never "troops".
local function is_static(u)
  return u.name == P.cfg.airbase_name or group_name(u) == P.cfg.airbase_name
         or starts(u.name, P.cfg.static_prefixes)
end

local function ground_counts(ctx)
  local att, def = 0, 0
  for name, guid in pairs(ctx.spawned) do
    if BL.starts_with(name, "UA_NG_") or BL.starts_with(name, "UA_CA_") then
      if inside(BL.get(guid)) then def = def + 1 end
    end
  end
  local side = VP_GetSide({side = P.cfg.attacker})
  for _, ref in ipairs(side.units or {}) do
    local u = BL.get(ref.guid)
    if u and u.type == "Facility" and not is_static(u) and inside(u) then att = att + 1 end
  end
  return att, def
end

local function flip_airbase(to_attacker)
  local from = to_attacker and P.cfg.defender or P.cfg.attacker
  local to = to_attacker and P.cfg.attacker or P.cfg.defender
  pcall(ScenEdit_SetUnitSide, {side = from, name = P.cfg.airbase_name, newside = to})
end

local function live_sams_near(ctx)
  local n = 0
  for name, guid in pairs(ctx.spawned) do
    if BL.starts_with(name, "UA_SAM_") then
      local u = BL.get(guid)
      if u and Tool_Range({latitude = P.center_lat, longitude = P.center_lon}, guid)
             <= P.cfg.threat_radius_nm then
        n = n + 1
      end
    end
  end
  return n
end

local function artillery_alive(ctx)
  local any_template = false
  for name, guid in pairs(ctx.spawned) do
    if BL.starts_with(name, "UA_ART_") then
      any_template = true
      if BL.get(guid) then return true end
    end
  end
  return not any_template   -- no artillery units modelled: fires are purely scripted
end

local function shell_runway(ctx, rate_per_hour, dt_h)
  if not P.cfg.shell_warhead_dbid then return end
  local segs = P.roles["BL_RWY"] or {}
  if #segs == 0 then return end
  local s = ctx.state
  s.shell_debt = s.shell_debt + rate_per_hour * dt_h
  while s.shell_debt >= 1 do
    s.shell_debt = s.shell_debt - 1
    local u = alive(ctx, segs[ctx.rng:int(1, #segs)])
    if u then
      pcall(ScenEdit_AddExplosion, {warheadid = P.cfg.shell_warhead_dbid,
            lat = tonumber(u.latitude) + ctx.rng:range(-0.0004, 0.0004),
            lon = tonumber(u.longitude) + ctx.rng:range(-0.0006, 0.0006), altitude = 0})
    end
  end
end

-- ---------------------------------------------------------------------------
-- Every tick
-- ---------------------------------------------------------------------------
function P.on_tick(ctx)
  local s, t = ctx.state, ctx.elapsed_h
  local dt_h = s.last_t and (t - s.last_t) or 0
  s.last_t = t

  -- 0. heliborne insertion ---------------------------------------------------
  deliver_vdv(ctx)

  -- 1. airfield control ------------------------------------------------------
  local att, def = ground_counts(ctx)
  local cand = (att > 0 and def == 0) and "attacker" or (def > 0 and att == 0) and "defender"
               or (att > 0 and def > 0) and "contested" or s.control
  if cand ~= s.candidate then s.candidate, s.candidate_since = cand, t end
  local held_long = (t - (s.candidate_since or t)) * 60 >= P.cfg.control_hold_minutes
  if cand ~= s.control and (cand == "contested" or held_long) then
    if cand == "attacker" then
      flip_airbase(true)
      if not s.t_control then
        s.t_control = t
        local clear = pv(ctx, "doctrine.clear_rate", 0.15)
        s.obstructed_until = t + pv(ctx, "denial.obstacles0", 0) / math.max(clear, 1e-6)
      end
    elseif cand == "defender" and s.control ~= "defender" then
      flip_airbase(false)
      if s.t_control then s.retakes = true end
    end
    if s.t_control and cand ~= "attacker" then s.lost_after = true end
    s.control = cand
  end

  -- 2. fires and demolition on the runway ------------------------------------
  local intensity = 0
  if t >= pv(ctx, "denial.t_fires", 1e9) and artillery_alive(ctx) then
    intensity = pv(ctx, "denial.fire_intensity", 0) * (1 - pv(ctx, "air.att.suppression", 0))
    if s.control ~= "defender" then
      shell_runway(ctx, P.cfg.max_shells_per_hour * intensity
                   * pv(ctx, "denial.crater_rate", 0) / 0.12, dt_h)
    end
  end
  if s.control == "defender" and s.t_control then
    shell_runway(ctx, P.cfg.max_demolitions_per_hour * pv(ctx, "denial.demolish_rate", 0), dt_h)
  end

  -- 3. airlift go / no-go ----------------------------------------------------
  local usable = P.runway_usable(ctx)
  local p_loss = pv(ctx, "air.att.approach_loss", 0) + P.cfg.fire_risk * intensity
                 + P.cfg.runway_risk * (1 - usable) + P.cfg.sam_risk * live_sams_near(ctx)
  local ok_now = s.control == "attacker" and usable >= P.cfg.r_min
                 and t >= (s.obstructed_until or 1e9)
                 and p_loss <= pv(ctx, "risk.tolerance", 1)
  local in_window = false
  for _, w in ipairs({pv(ctx, "ctx.wave1_t", 4.5), pv(ctx, "ctx.wave2_t", 26)}) do
    if t >= w - P.cfg.il76_flight_h and t <= w + P.cfg.loiter_h then in_window = true end
  end
  if not s.released and in_window and ok_now then
    set_airlift(true)
    s.released, s.t_release = true, t
    BL.log(("run %s: Il-76 released at H+%.2f (p_loss %.3f)"):format(ctx.run.id, t, p_loss))
  elseif s.released and not s.aborted and s.control ~= "attacker" and #s.landed_list == 0 then
    set_airlift(false)
    s.aborted = true
    BL.log(("run %s: Il-76 recalled at H+%.2f"):format(ctx.run.id, t))
  end

  -- 4. landed / lost transports ---------------------------------------------
  for _, name in ipairs(P.roles["RU_IL76_"] or {}) do
    if not s.landed_at[name] and not s.lost_il76[name] and ctx.spawned[name] then
      local u = BL.get(ctx.spawned[name])
      if not u then
        s.lost_il76[name] = true
      else
        local ok, base = pcall(function() return u.base and u.base.name end)
        if ok and base == P.cfg.airbase_name and s.released then
          s.landed_at[name] = t
          s.landed_list[#s.landed_list + 1] = name
          s.first_landing = s.first_landing or t
        end
      end
    end
  end
  local troops = #s.landed_list * P.cfg.troops_per_aircraft
  if not s.t_airbridge and troops >= P.cfg.airbridge_troops then s.t_airbridge = t end
end

-- ---------------------------------------------------------------------------
-- End of run
-- ---------------------------------------------------------------------------
function P.evaluate(ctx)
  local s = ctx.state
  local troops = #s.landed_list * P.cfg.troops_per_aircraft
  local helos_lost = 0
  for _, name in ipairs(P.roles["RU_HELO_T_"] or {}) do
    if ctx.spawned[name] and not BL.get(ctx.spawned[name]) then helos_lost = helos_lost + 1 end
  end
  local lost = 0
  for _ in pairs(s.lost_il76) do lost = lost + 1 end
  return {
    landed = troops, airbridge = troops >= P.cfg.airbridge_troops,
    t_airbridge = s.t_airbridge, t_first_landing = s.first_landing, transports_lost = lost,
    t_control = s.t_control, attacker_ever_controls = s.t_control ~= nil,
    attacker_lost_control = s.lost_after, attacker_holds_end = s.control == "attacker",
    defender_retakes = s.retakes, runway_end = P.runway_usable(ctx),
    released = s.released, t_release = s.t_release, helos_lost = helos_lost,
    sams_kept = s.kept and s.kept.sam, garrison_kept = s.kept and s.kept.ng,
    counterattack_kept = s.kept and s.kept.ca, vdv_delivered = s.vdv_delivered,
  }
end

-- ---------------------------------------------------------------------------
-- Scenario-specific self-test items
-- ---------------------------------------------------------------------------
function P.selftest(template)
  local out = {}
  local by = {}
  for _, r in ipairs(template) do
    for _, pre in ipairs({"RU_HELO_T_", "RU_IL76_", "UA_NG_", "UA_CA_", "UA_SAM_", "BL_RWY"}) do
      if BL.starts_with(r.name, pre) then by[pre] = (by[pre] or 0) + 1 end
    end
  end
  for _, pre in ipairs({"RU_HELO_T_", "RU_IL76_", "UA_NG_", "UA_CA_", "BL_RWY"}) do
    out[#out + 1] = {"units named " .. pre .. "*", (by[pre] or 0) > 0, "(" .. (by[pre] or 0) .. ")"}
  end
  local vdv = 0
  for _, r in ipairs(template) do if BL.starts_with(r.name, "RU_VDV_") then vdv = vdv + 1 end end
  out[#out + 1] = {"units named RU_VDV_* (scripted heliborne squads)", vdv > 0, "(" .. vdv .. ")"}
  local ok = pcall(BL.polygon, P.cfg.attacker, P.cfg.airfield_rps)
  out[#out + 1] = {"airfield reference points", ok}
  local okm, m = pcall(ScenEdit_GetMission, P.cfg.attacker, P.cfg.airlift_mission)
  out[#out + 1] = {"mission '" .. P.cfg.airlift_mission .. "'", okm and m ~= nil}
  local found = false
  for _, r in ipairs(template) do if r.name == P.cfg.airbase_name then found = true end end
  out[#out + 1] = {"airbase '" .. P.cfg.airbase_name .. "'", found}
  out[#out + 1] = {"shell_warhead_dbid configured", P.cfg.shell_warhead_dbid ~= nil,
                   "(needed for scripted runway fires)"}
  return out
end

return BL_HOSTOMEL
