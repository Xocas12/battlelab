--[[
Database IDs for bl_build_hostomel.lua and bl_run.lua. THE ONLY FILE YOU EDIT.

DBIDs differ between CMO database versions, so they cannot be shipped. Look
each one up in the Database Viewer (Editor > Database Viewer, or the unit's
"Show DB info"), for the database your scenario uses, and replace the nils.
Pick anything reasonable; the entries in parentheses are suggestions.

Loadout IDs: open the aircraft in the Database Viewer, Loadouts tab. For
transports use a ferry / cargo / "Reserve" loadout, not a strike loadout.
]]
BL_BUILD_DB = {
  -- facilities (ground units are facilities in CMO) ----------------------------
  airfield       = nil,  -- a single-unit airfield that can host aircraft
                         --   (e.g. "Airfield (2000-3000m runway)" / "Air Base (Large)")
  runway_segment = nil,  -- a runway or runway-section facility (for BL_RWY_1..4);
                         --   may be the same as airfield if nothing better exists
  ua_infantry    = nil,  -- Ukrainian infantry section/platoon (garrison and counterattack)
  ua_sam         = nil,  -- short-range SAM (e.g. 9K35 Strela-10, 9K33 Osa, Igla team)
  ua_artillery   = nil,  -- towed or SP howitzer battery (e.g. 2S1, 2S3, D-30)
  ru_infantry    = nil,  -- Russian airborne (VDV) infantry section/platoon
  ru_mech        = nil,  -- Russian mechanised platoon (BMD / BTR / BMP) for the relief column
  -- aircraft ---------------------------------------------------------------------
  mi8            = nil,  -- Mi-8AMTSh / Mi-8MTV transport helicopter
  mi8_loadout    = nil,  -- its cargo / troop-transport loadout ID
  il76           = nil,  -- Il-76MD transport
  il76_loadout   = nil,  -- its cargo / ferry loadout ID
  -- weapon -------------------------------------------------------------------------
  shell_warhead  = nil,  -- an HE artillery warhead (Weapons, e.g. 152mm HE) used for the
                         --   scripted shelling of the runway; nil = no scripted fires
}
