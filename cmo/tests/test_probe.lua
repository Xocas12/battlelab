--[[ Runs bl_probe.lua against the mock CMO API.
usage: lua5.3 tests/test_probe.lua <lua_dir> <out_dir> [--write] ]]
local lua_dir, out_dir, flag = arg[1], arg[2], arg[3]
local here = arg[0]:match("(.*/)") or "./"
dofile(here .. "mock_cmo.lua")
MOCK.lua_dir = lua_dir
_scenariofolder_ = out_dir
ScenEdit_AddUnit({type = "Facility", name = "Airbase", side = "Ukraine", dbid = 1, latitude = 50.6, longitude = 30.2})
ScenEdit_AddUnit({type = "Facility", name = "Rifle Sqn", side = "Ukraine", dbid = 2, latitude = 50.61, longitude = 30.21})
ScenEdit_AddUnit({type = "Aircraft", name = "Transport 1", side = "Russia", dbid = 3, latitude = 51, longitude = 30, base = "Airbase", loadoutid = 7})
BL_PROBE_WRITE = (flag == "--write")
local lines = dofile(lua_dir .. "/battlelab/bl_probe.lua")
local seen = {}
for _, l in ipairs(lines) do seen[l:match("^BLPROBE|([^|]+)|")] = l:match("|([^|]*)$") end
local function need(k, pat)
  local v = seen[k]
  if not v or (pat and not v:match(pat)) then
    io.stderr:write("FAIL " .. k .. " = " .. tostring(v) .. "\n"); os.exit(1)
  end
end
need("api.ScenEdit_AddUnit", "true")
need("count.Facility")
need("unit[Aircraft(based)].base.name")
need("done")
if BL_PROBE_WRITE then need("write.add_unit", "ok"); need("write.delete", "ok") end
io.write("PROBE OK (" .. #lines .. " lines)\n")
if os.getenv("BLPROBE_SHOW") then io.write(table.concat(lines, "\n"), "\n") end
