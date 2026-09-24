"""Zone control, runway engineering, air-landing and outcome metrics."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..engine import Mechanic, Phase
from ..state import World


class Control(Mechanic):
    """A zone belongs to the only side with active units in it.

    Empty zones keep their last controller; zones with both sides are
    'contested'. When a side takes a zone its units there switch to defence
    with the side's `hasty_defense` multiplier.
    """
    phase = Phase.CONTROL
    name = "control"

    def step(self, w: World):
        for z in w.zones.values():
            sides = {u.side for u in w.units_in(z.id)}
            new = z.control
            if len(sides) == 1:
                new = next(iter(sides))
            elif len(sides) > 1:
                new = "contested"
            if new != z.control:
                w.emit("control", zone=z.id, old=z.control, new=new)
                if new in w.sides:
                    bonus = w.sides[new].doctrine.get("hasty_defense", 1.0)
                    for u in w.units_in(z.id, new):
                        u.posture = "defend"
                        u.dug_in = max(u.dug_in, bonus)
                z.control = new


class RunwayEngineering(Mechanic):
    """Controller clears obstacles (doctrine `clear_rate`) or demolishes the
    runway (doctrine `demolish_rate`), both per hour."""
    phase = Phase.ENGINEERING
    name = "engineering"

    def step(self, w: World):
        for z in w.zones.values():
            if z.runway is None or z.control not in w.sides:
                continue
            d = w.sides[z.control].doctrine
            r = z.runway
            r.obstacles = max(0.0, r.obstacles - d.get("clear_rate", 0.0) * w.dt)
            r.craters = min(1.0, r.craters + d.get("demolish_rate", 0.0) * w.dt)


@dataclass
class AirliftSpec:
    side: str
    zone: str
    unit_id: str                     # unit that receives the landed troops
    aircraft: int
    troops_per_aircraft: float
    mode: str = "waves"              # waves | shuttle
    waves: list[float] = field(default_factory=list)   # arrival times (waves)
    loiter_h: float = 1.5            # waves: how long a wave waits before aborting
    interval_h: float = 3.0          # shuttle: time between sorties
    first_after_control_h: float = 0.0   # shuttle: delay after first control
    daylight_only: bool = False
    r_min: float = 0.6               # usable runway fraction needed
    fire_risk: float = 0.25          # loss prob per unit of enemy fire intensity
    runway_risk: float = 0.10        # loss prob per unit of unusable runway
    crash_survival: float = 0.5      # troops surviving a lost aircraft
    wreck_obstacle: float = 0.004    # runway blocked per wrecked aircraft
    organisation: float = 0.9        # fraction of landed troops combat-ready
    go_rule: str = "threshold"       # threshold | logistic
    go_width: float = 0.02           # logistic: scale of the acceptance curve
    info_lag_h: float = 0.0          # risk estimate lags the true risk by this long


GO_RULES = ("threshold", "logistic")


class Airlift(Mechanic):
    """Air-landing with an explicit go/no-go rule.

    expected loss per aircraft
        p = own approach_loss + fire_risk * enemy fire on zone
            + runway_risk * (1 - usable runway)
    A wave (or shuttle sortie) lands only if the side holds the zone, the
    runway is at least r_min usable, the risk estimate is acceptable and
    (optionally) it is day. Two acceptance rules:

      threshold  accept iff p_est <= risk_tolerance (deterministic cliff)
      logistic   each wave/sortie draws its own nerve u ~ U(0,1) once and
                 accepts iff p_est <= tolerance + go_width * logit(u), so a
                 single decision accepts with probability
                 1 / (1 + exp((p_est - tolerance) / go_width))

    p_est is the true p from `info_lag_h` hours earlier (reports reach the
    decision maker late); with info_lag_h = 0 it is the current p.
    """
    phase = Phase.AIRLIFT
    name = "airlift"

    def __init__(self, spec: AirliftSpec):
        if spec.go_rule not in GO_RULES:
            raise ValueError(f"unknown go_rule {spec.go_rule!r}; have {GO_RULES}")
        self.s = spec

    def setup(self, w: World):
        w.persist["airlift"] = {"landed": 0.0, "lost": 0, "waves": [None] * len(self.s.waves),
                                "next_slot": math.inf, "first_landing": None,
                                "p_hist": [], "nerve": {}}
        w.metrics.setdefault("landed", 0.0)

    def p_loss(self, w: World) -> float:
        s = self.s
        enemy = w.enemy_of(s.side)
        fire = w.scratch.get("fire", {}).get((enemy, s.zone), 0.0)
        r = w.zones[s.zone].runway
        p = (w.sides[s.side].air.approach_loss + s.fire_risk * fire
             + s.runway_risk * (1.0 - r.usable))
        return min(max(p, 0.0), 0.95)

    def p_estimate(self, w: World) -> float:
        """The risk as the decision maker sees it (lagged by info_lag_h)."""
        hist = w.persist["airlift"]["p_hist"]
        if self.s.info_lag_h <= 0 or not hist:
            return self.p_loss(w)
        t_seen = w.t - self.s.info_lag_h
        seen = hist[0][1]
        for t, p in hist:
            if t > t_seen + 1e-9:
                break
            seen = p
        return seen

    def tolerance(self, w: World, key: str) -> float:
        tol = w.sides[self.s.side].doctrine.get("risk_tolerance", 1.0)
        if self.s.go_rule == "threshold":
            return tol
        nerve = w.persist["airlift"]["nerve"]
        if key not in nerve:
            u = float(w.rng("airlift_decision").random())
            u = min(max(u, 1e-9), 1 - 1e-9)
            nerve[key] = self.s.go_width * math.log(u / (1 - u))
        return tol + nerve[key]

    def conditions(self, w: World, p_est: float, key: str = "") -> bool:
        s = self.s
        z = w.zones[s.zone]
        if not (z.control == s.side and z.runway.usable >= s.r_min):
            return False
        if s.daylight_only and not w.is_day():
            return False
        return p_est <= self.tolerance(w, key)

    def land(self, w: World, p: float, label: str):
        s, st = self.s, w.persist["airlift"]
        lost = int(w.rng("airlift").binomial(s.aircraft, p))
        troops = (s.aircraft - lost) * s.troops_per_aircraft \
            + lost * s.troops_per_aircraft * s.crash_survival
        u = w.units[s.unit_id]
        add = troops * s.organisation
        if u.status == "active":
            u.strength += add
        else:
            u.strength = add
            u.activate(s.zone, w.t, "defend")
            u.dug_in = max(u.dug_in, w.sides[s.side].doctrine.get("hasty_defense", 1.0))
        u.peak = max(u.peak, u.strength)
        r = w.zones[s.zone].runway
        r.obstacles = min(1.0, r.obstacles + s.wreck_obstacle * lost)
        st["landed"] += troops
        st["lost"] += lost
        if st["first_landing"] is None:
            st["first_landing"] = w.t
        w.emit("airlanding", wave=label, aircraft=s.aircraft, lost=lost,
               troops=round(troops), p_loss=round(p, 3))

    def step(self, w: World):
        s, st = self.s, w.persist["airlift"]
        p = self.p_loss(w)
        if s.info_lag_h > 0:
            st["p_hist"].append((w.t, p))
            while len(st["p_hist"]) > 2 and st["p_hist"][1][0] < w.t - s.info_lag_h - 1e-9:
                st["p_hist"].pop(0)
        p_est = self.p_estimate(w)
        if s.mode == "waves":
            for i, t0 in enumerate(s.waves):
                if st["waves"][i] is not None or w.t < t0:
                    continue
                if self.conditions(w, p_est, f"wave{i}"):
                    self.land(w, p, f"wave{i + 1}")
                    st["waves"][i] = "landed"
                    p = self.p_loss(w)
                    if s.info_lag_h <= 0:
                        p_est = p
                elif w.t > t0 + s.loiter_h:
                    st["waves"][i] = "aborted"
                    w.emit("airlift_abort", wave=f"wave{i + 1}", p_loss=round(p, 3),
                           p_est=round(p_est, 3), control=w.zones[s.zone].control,
                           runway=round(w.zones[s.zone].runway.usable, 2))
        else:
            t_ctrl = w.persist.get("first_control", {}).get((s.side, s.zone))
            if math.isinf(st["next_slot"]) and t_ctrl is not None:
                st["next_slot"] = t_ctrl + s.first_after_control_h
            if w.t >= st["next_slot"]:
                key = f"sortie{int(st.get('sorties', 0))}"
                if self.conditions(w, p_est, key):
                    self.land(w, p, "sortie")
                    st["sorties"] = st.get("sorties", 0) + 1
                    st["next_slot"] = w.t + s.interval_h
                else:
                    st["next_slot"] = w.t + 0.5
        w.metrics["landed"] = st["landed"]


class FirstControlTracker(Mechanic):
    """Remembers when each side first held each zone (used by others)."""
    phase = Phase.CONTROL + 1   # runs right after Control
    name = "first_control"

    def step(self, w: World):
        fc = w.persist.setdefault("first_control", {})
        for z in w.zones.values():
            if z.control in w.sides and (z.control, z.id) not in fc:
                fc[(z.control, z.id)] = w.t


@dataclass
class OutcomeSpec:
    zone: str
    airbridge_troops: float = 500.0


class Outcome(Mechanic):
    """Writes the standard airhead metrics at the end of the run."""
    phase = Phase.RECORD
    name = "outcome"

    def __init__(self, spec: OutcomeSpec):
        self.s = spec

    def step(self, w: World):
        st = w.persist.get("airlift", {})
        if w.metrics.get("t_airbridge") is None and \
                st.get("landed", 0.0) >= self.s.airbridge_troops:
            w.metrics["t_airbridge"] = w.t

    def finalize(self, w: World):
        att, dfn = w.attacker(), w.defender()
        z = w.zones[self.s.zone]
        st = w.persist.get("airlift", {})
        fc = w.persist.get("first_control", {})
        ctrl_events = [e for e in w.log if e.kind == "control" and e.data["zone"] == z.id]
        t_att = fc.get((att, z.id))
        lost_after = t_att is not None and any(
            e.t > t_att and e.data["new"] != att for e in ctrl_events)
        m = w.metrics
        m.update(
            landed=st.get("landed", 0.0),
            airbridge=st.get("landed", 0.0) >= self.s.airbridge_troops,
            t_airbridge=m.get("t_airbridge"),
            t_first_landing=st.get("first_landing"),
            transports_lost=st.get("lost", 0),
            t_control=t_att,
            attacker_ever_controls=t_att is not None,
            attacker_lost_control=lost_after,
            attacker_holds_end=z.control == att,
            defender_retakes=t_att is not None and any(
                e.t > t_att and e.data["new"] == dfn for e in ctrl_events),
            runway_end=z.runway.usable if z.runway else None,
            losses_attacker=sum(u.peak - u.strength for u in w.units.values()
                                if u.side == att and u.peak > 0),
            losses_defender=sum(u.peak - u.strength for u in w.units.values()
                                if u.side == dfn and u.peak > 0),
        )
