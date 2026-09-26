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
    * (1 - shock(t))                             surprise of an enemy air landing
                                                 in this zone: shock0 * exp(-dt/decay)
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
# calibrated model. Against the Lanchester resolver at the family's kill rate
# it is 2-6x bloodier per hour and much kinder to defenders at low odds (see
# `expected_loss_rates` and `battlelab resolvers`). Purely illustrative.
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
        e *= 1.0 + self.fw[u.posture] * fire
        shock = w.persist.get("shock", {}).get((u.zone, enemy))
        if shock is not None:
            t0, mag, decay = shock
            e *= 1.0 - mag * math.exp(-(w.t - t0) / decay)
        return e

    def step(self, w: World):
        w.scratch["engaged"] = {}
        w.scratch["side_strength"] = {}
        for zid in w.zones:
            present = w.units_in(zid)
            sides = sorted({u.side for u in present})   # sorted: set order varies by process
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
            return max(sorted({u.side for u in att}),
                       key=lambda s: sum(u.strength for u in att if u.side == s))
        return w.attacker()


class MoraleCheck(Mechanic):
    """Per-hour hazard of leaving the fight, for every engaged unit.

    hazard = base
           + ratio_coeff    * ratio_scale * max(enemy_eff / own_eff - 1, 0)
           + casualty_coeff * (1 - strength / peak)
           + ammo_hazard    * [ammo exhausted]
    plus immediate departure when the ratio exceeds `withdraw_ratio`, a
    commitment timeout for counterattacks and forced CRT retreats.

    Command decision cycle (`Morale.decision_h > 0`): the base, ratio and
    casualty terms are not applied every turn. Instead the commander evaluates
    them at decision points every `decision_h` hours and orders a withdrawal
    with probability 1 - exp(-hazard * decision_h). With probability
    `comms_loss` a decision is taken without reports from the forward
    elements, and the commander then assumes at least `fog` casualties. With
    `night_moves` an order is only executed in darkness, and with
    `move_delay_h` > 0 only after an exponential delay from the moment it
    becomes executable. Immediate exits
    (collapse, outmatched, commitment, ammunition, forced retreat) are
    unaffected: they are the troops' own reaction, not the commander's. With
    decision_h <= dt, no comms loss and no night rule this reduces exactly to
    the continuous hazard.
    """
    phase = Phase.MORALE
    name = "morale"

    def __init__(self, ratio_coeff=0.10, casualty_coeff=0.30, ammo_hazard=2.0,
                 retreat_check_hazard=1.5, collapse_fraction=0.05):
        self.B0, self.HC, self.AMMO = ratio_coeff, casualty_coeff, ammo_hazard
        self.retreat_hz = retreat_check_hazard
        self.collapse = collapse_fraction

    @staticmethod
    def commanded(m, dt: float) -> bool:
        return m.decision_h > dt + 1e-9 or m.comms_loss > 0 or bool(m.night_moves)

    def judged_hazard(self, m, ratio: float, casualties: float) -> float:
        return (m.base_hazard + self.B0 * m.ratio_scale * max(ratio - 1.0, 0.0)
                + self.HC * casualties)

    def step(self, w: World):
        engaged = w.scratch.get("engaged", {})
        forced = w.scratch.get("forced_retreat", set())
        orders = w.persist.setdefault("withdraw_orders", {})
        g = w.rng("morale")
        for uid, (own, enemy) in engaged.items():
            u = w.units[uid]
            if not u.active:
                continue
            m = u.morale
            ratio = enemy / max(own, 1e-9)
            casualties = 1.0 - u.strength / max(u.peak, 1e-9)
            reason = None
            if u.strength <= self.collapse * max(u.peak, 1e-9):
                reason = "collapse"
            elif ratio > m.withdraw_ratio:
                reason = "outmatched"
            elif u.posture == "attack" and u.arrived_at is not None \
                    and w.t - u.arrived_at > m.commit_h:
                reason = "commitment_expired"
            elif self.commanded(m, w.dt):
                self._command(w, u, ratio, casualties)
                hz = 0.0
                if u.first_contact is not None and w.t - u.first_contact >= m.ammo_out_h:
                    hz += self.AMMO
                if (u.zone, u.side) in forced:
                    hz += self.retreat_hz
                if hz > 0 and g.random() < 1.0 - math.exp(-hz * w.dt):
                    reason = "morale"
                elif uid in orders and (not m.night_moves or not w.is_day()) \
                        and self._ready(w, uid, m):
                    reason = "ordered_withdrawal"
            else:
                hz = self.judged_hazard(m, ratio, casualties)
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
                orders.pop(uid, None)

    @staticmethod
    def _ready(w: World, uid: str, m) -> bool:
        """An executable order is carried out after an exponential delay
        (mean move_delay_h: orders reach the companies, the move is organised)."""
        if m.move_delay_h <= 0:
            return True
        ready = w.persist.setdefault("order_ready", {})
        if uid not in ready:
            ready[uid] = w.t + float(w.rng("command").exponential(m.move_delay_h))
        return w.t + 1e-9 >= ready[uid]

    def _command(self, w: World, u, ratio: float, casualties: float):
        """One commander decision if a decision point falls in this turn."""
        m = u.morale
        nxt = w.persist.setdefault("next_decision", {})
        cycle = max(m.decision_h, w.dt)
        if w.t + 1e-9 < nxt.get(u.id, cycle) or u.id in w.persist["withdraw_orders"]:
            return
        nxt[u.id] = (math.floor(w.t / cycle + 1e-9) + 1) * cycle
        g = w.rng("command")
        blind = g.random() < m.comms_loss
        seen = max(casualties, m.fog) if blind else casualties
        hz = self.judged_hazard(m, ratio, seen)
        order = g.random() < 1.0 - math.exp(-hz * cycle)
        w.emit("command_decision", unit=u.id, blind=blind, perceived_casualties=round(seen, 2),
               ratio=round(ratio, 2), order="withdraw" if order else "hold")
        if order:
            w.persist["withdraw_orders"][u.id] = w.t


def expected_loss_rates(odds: list[float], kill_rate: float = 0.01,
                        round_h: float = 1.0) -> list[dict]:
    """Expected hourly loss fractions per side under each resolver.

    Reference engagement: both sides at quality 1, no posture or fire
    modifiers, so effective strength equals strength and odds = A / D.
    Lanchester: attacker loses kill_rate * D per hour, i.e. a fraction
    kill_rate / odds; the defender a fraction kill_rate * odds. CRT: the d6
    expectation of the odds column, per round of `round_h` hours. The
    retreat result is not included (it acts through morale, not attrition).
    """
    rows = []
    for o in odds:
        col = sum(o >= c for c in CRT_COLUMNS[1:])
        cells = CRT_TABLE[col]
        crt_a = sum(c[0] for c in cells) / 6 / round_h
        crt_d = sum(c[1] for c in cells) / 6 / round_h
        p_dr = sum(c[2] for c in cells) / 6
        rows.append({"odds": o, "lan_att": kill_rate / o, "lan_def": kill_rate * o,
                     "crt_att": crt_a, "crt_def": crt_d, "crt_p_retreat": p_dr,
                     "lan_exchange": (kill_rate * o) / (kill_rate / o) if o else float("nan"),
                     "crt_exchange": crt_d / crt_a if crt_a else float("inf")})
    return rows
