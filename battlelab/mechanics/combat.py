"""Combat and morale.

Combat computes each side's *effective strength* in every contested zone and
hands the pair to a resolver. Two resolvers ship with the framework so that
structural uncertainty (the choice of attrition model) can be tested, not just
parameter uncertainty:

  * LanchesterPoisson - continuous stochastic Lanchester square law.
  * CRTResolver       - a board-game combat results table (odds column + d6),
                        resolved in rounds of fixed length.

Effective strength of a unit =
    strength * quality
    * (dug_in if defending)                      prepared / hasty positions
    * (1 - enemy interdiction if attacking)      air attack on the move
    * own CAS multiplier                         close air support
    * (1 + w_posture * own fire intensity here)  artillery / bombardment
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..engine import Mechanic, Phase
from ..state import BROKEN, WITHDRAWN, World


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------
class Resolver:
    name = "resolver"

    def resolve(self, w: World, zone: str, eff: dict[str, float],
                attacker: str) -> dict[str, float]:
        """Return personnel losses per side for this turn."""
        raise NotImplementedError


@dataclass
class LanchesterPoisson(Resolver):
    kill_rate: float = 0.01      # casualties per effective shooter-hour
    name = "lanchester"

    def resolve(self, w, zone, eff, attacker):
        a, b = list(eff)
        g = w.rng("combat")
        return {a: float(g.poisson(self.kill_rate * eff[b] * w.dt)),
                b: float(g.poisson(self.kill_rate * eff[a] * w.dt))}


# Odds columns (attacker:defender) and d6 outcomes. Each cell gives the
# fraction of strength lost per round by (attacker, defender) and whether the
# defender must take an immediate retreat check. Generic table in the style of
# classic hex-and-counter games; it is a structural alternative, not a
# calibrated model, and is flagged as such in the docs.
CRT_COLUMNS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)
_AE, _AR, _EX, _DR, _DE = ((0.12, 0.00, False), (0.06, 0.01, False),
                           (0.05, 0.05, False), (0.02, 0.04, True),
                           (0.02, 0.12, True))
CRT_TABLE = (
    #  d6:  1     2     3     4     5     6
    (_AE, _AE, _AE, _AR, _AR, _EX),   # < 1:1
    (_AE, _AR, _AR, _EX, _EX, _DR),   # 1:1
    (_AR, _AR, _EX, _EX, _DR, _DR),   # 1.5:1
    (_AR, _EX, _EX, _DR, _DR, _DE),   # 2:1
    (_EX, _EX, _DR, _DR, _DE, _DE),   # 3:1
    (_EX, _DR, _DR, _DE, _DE, _DE),   # 4:1
    (_DR, _DR, _DE, _DE, _DE, _DE),   # 5:1+
)


@dataclass
class CRTResolver(Resolver):
    round_h: float = 1.0
    name = "crt"

    def resolve(self, w, zone, eff, attacker):
        store = w.persist.setdefault("crt_clock", {})
        clock = store.get(zone, 0.0) + w.dt
        if clock + 1e-9 < self.round_h:
            store[zone] = clock
            return {s: 0.0 for s in eff}
        store[zone] = 0.0
        defender = next(s for s in eff if s != attacker)
        odds = eff[attacker] / max(eff[defender], 1e-9)
        col = sum(odds >= c for c in CRT_COLUMNS[1:])
        roll = int(w.rng("crt").integers(0, 6))
        a_frac, d_frac, retreat = CRT_TABLE[col][roll]
        if retreat:
            w.scratch.setdefault("forced_retreat", set()).add((zone, defender))
        strength = w.scratch["side_strength"][zone]
        w.emit("crt", zone=zone, odds=round(odds, 2), roll=roll + 1,
               result=("AE", "AR", "EX", "DR", "DE")[
                   [_AE, _AR, _EX, _DR, _DE].index(CRT_TABLE[col][roll])])
        return {attacker: a_frac * strength[attacker],
                defender: d_frac * strength[defender]}


RESOLVERS = {"lanchester": LanchesterPoisson, "crt": CRTResolver}


# ---------------------------------------------------------------------------
# Combat mechanic
# ---------------------------------------------------------------------------
class Combat(Mechanic):
    phase = Phase.COMBAT
    name = "combat"

    def __init__(self, resolver: Resolver, fire_weight_defend: float = 1.0,
                 fire_weight_attack: float = 2.0):
        self.resolver = resolver
        self.fw = {"defend": fire_weight_defend, "attack": fire_weight_attack}

    def unit_eff(self, w: World, u) -> float:
        s = w.scratch
        enemy = w.enemy_of(u.side)
        e = u.strength * u.quality * s["cas"][u.side]
        if u.posture == "defend":
            e *= u.dug_in
        else:
            e *= 1.0 - s["interdict"][enemy]
        fire = s.get("fire", {}).get((u.side, u.zone), 0.0)
        return e * (1.0 + self.fw[u.posture] * fire)

    def step(self, w: World):
        w.scratch["engaged"] = {}
        w.scratch["side_strength"] = {}
        for zid in w.zones:
            present = w.units_in(zid)
            sides = {u.side for u in present}
            if len(sides) < 2:
                continue
            eff = {s: 0.0 for s in sides}
            strength = {s: 0.0 for s in sides}
            for u in present:
                eff[u.side] += self.unit_eff(w, u)
                strength[u.side] += u.strength
                if u.first_contact is None:
                    u.first_contact = w.t
            w.scratch["side_strength"][zid] = strength
            att = self._attacking_side(w, present)
            losses = self.resolver.resolve(w, zid, eff, att)
            for side, loss in losses.items():
                mine = [u for u in present if u.side == side]
                total = sum(u.strength for u in mine)
                for u in mine:
                    u.strength = max(0.0, u.strength - loss * u.strength / max(total, 1e-9))
            for u in present:
                enemy = w.enemy_of(u.side)
                w.scratch["engaged"][u.id] = (eff[u.side], eff[enemy])

    @staticmethod
    def _attacking_side(w, present):
        att = [u for u in present if u.posture == "attack"]
        if att:
            return max({u.side for u in att},
                       key=lambda s: sum(u.strength for u in att if u.side == s))
        return w.attacker()


class MoraleCheck(Mechanic):
    """Per-hour hazard of leaving the fight, for every engaged unit.

    hazard = base
           + ratio_coeff    * max(enemy_eff / own_eff - 1, 0)
           + casualty_coeff * (1 - strength / peak)
           + ammo_hazard    * [ammo exhausted]
    plus immediate departure when the ratio exceeds `withdraw_ratio`, a
    commitment timeout for counterattacks and forced CRT retreats.
    """
    phase = Phase.MORALE
    name = "morale"

    def __init__(self, ratio_coeff=0.10, casualty_coeff=0.30, ammo_hazard=2.0,
                 retreat_check_hazard=1.5, collapse_fraction=0.05):
        self.B0, self.HC, self.AMMO = ratio_coeff, casualty_coeff, ammo_hazard
        self.retreat_hz = retreat_check_hazard
        self.collapse = collapse_fraction

    def step(self, w: World):
        engaged = w.scratch.get("engaged", {})
        forced = w.scratch.get("forced_retreat", set())
        g = w.rng("morale")
        for uid, (own, enemy) in engaged.items():
            u = w.units[uid]
            if not u.active:
                continue
            m = u.morale
            ratio = enemy / max(own, 1e-9)
            reason = None
            if u.strength <= self.collapse * max(u.peak, 1e-9):
                reason = "collapse"
            elif ratio > m.withdraw_ratio:
                reason = "outmatched"
            elif u.posture == "attack" and u.arrived_at is not None \
                    and w.t - u.arrived_at > m.commit_h:
                reason = "commitment_expired"
            else:
                hz = (m.base_hazard + self.B0 * max(ratio - 1.0, 0.0)
                      + self.HC * (1.0 - u.strength / max(u.peak, 1e-9)))
                if u.first_contact is not None and w.t - u.first_contact >= m.ammo_out_h:
                    hz += self.AMMO
                if (u.zone, u.side) in forced:
                    hz += self.retreat_hz
                if g.random() < 1.0 - math.exp(-hz * w.dt):
                    reason = "morale"
            if reason:
                u.status = BROKEN if m.on_break == "disperse" else WITHDRAWN
                w.emit("leaves_fight", unit=u.id, reason=reason, status=u.status,
                       strength=round(u.strength, 1), ratio=round(ratio, 2))
                u.zone = None
