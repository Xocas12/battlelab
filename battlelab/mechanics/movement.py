"""Arrivals (ground, heliborne, parachute), air situation and fires."""
from __future__ import annotations

from dataclasses import dataclass

from ..engine import Mechanic, Phase
from ..state import PENDING, World

AIR_MODES = ("air_assault", "parachute", "glider")


@dataclass
class ArrivalSpec:
    unit_id: str
    t: float
    zone: str
    mode: str = "ground"            # ground | air_assault | parachute | glider
    aircraft: int = 0
    capacity: float = 0.0
    dz_loss: float = 0.0            # fraction lost on landing / in the drop zone
    only_if_present: bool = False   # e.g. airborne reserves: only drop if own
                                    # troops still hold or contest the zone
    shock: float = 0.0              # surprise: initial fractional loss of enemy
                                    # effectiveness in the zone (air arrivals only)
    shock_decay_h: float = 2.0      # e-folding time of that shock


class Arrivals(Mechanic):
    """Brings pending units onto the map at their scheduled time.

    Air-delivered units lose aircraft to ingress (the arriving side's
    `air.ingress_loss`, binomial per aircraft) and a drop-zone fraction.
    Posture on arrival: defend if the zone is empty or already ours,
    attack otherwise.
    """
    phase = Phase.SCHEDULE
    name = "arrivals"

    def __init__(self, arrivals: list[ArrivalSpec]):
        self.arrivals = sorted(arrivals, key=lambda a: a.t)

    def step(self, w: World):
        for a in self.arrivals:
            u = w.units[a.unit_id]
            if u.status != PENDING or w.t < a.t:
                continue
            zone = w.zones[a.zone]
            if a.only_if_present and not w.units_in(a.zone, u.side):
                u.status = "cancelled"
                w.emit("arrival_cancelled", unit=u.id)
                continue
            if a.mode in AIR_MODES and a.aircraft <= 0:
                u.status = "cancelled"
                continue
            if a.mode in AIR_MODES:
                p_loss = w.sides[u.side].air.ingress_loss
                survivors = int(w.rng("ingress").binomial(a.aircraft, 1.0 - p_loss))
                u.strength = survivors * a.capacity * (1.0 - a.dz_loss)
                w.emit("insertion", unit=u.id, aircraft=a.aircraft,
                       aircraft_lost=a.aircraft - survivors, strength=round(u.strength, 1))
            if u.strength <= 0:
                u.status = "cancelled"
                w.emit("arrival_cancelled", unit=u.id, reason="zero strength")
                continue
            if a.mode in AIR_MODES and a.shock > 0 and zone.control != u.side:
                shocks = w.persist.setdefault("shock", {})
                shocks[(a.zone, u.side)] = (w.t, a.shock, max(a.shock_decay_h, 1e-6))
                w.emit("shock", zone=a.zone, by=u.side, magnitude=round(a.shock, 2))
            enemy_here = any(x.side != u.side for x in w.units_in(a.zone))
            held_by_enemy = zone.control not in (None, u.side)
            posture = "attack" if (held_by_enemy or (enemy_here and zone.control != u.side)) \
                else "defend"
            u.activate(a.zone, w.t, posture)
            w.emit("arrival", unit=u.id, zone=a.zone, posture=posture,
                   strength=round(u.strength, 1))


class AirSituation(Mechanic):
    """Per-turn air effects, scaled down at night where air power is day-only."""
    phase = Phase.AIR
    name = "air"

    def step(self, w: World):
        cas, supp, interdict = {}, {}, {}
        for sid, side in w.sides.items():
            k = w.air_scale(sid)
            cas[sid] = 1.0 + (side.air.cas - 1.0) * k
            supp[sid] = side.air.suppress_enemy_fires * k
            interdict[sid] = side.air.interdiction * k
        w.scratch.update(cas=cas, suppress=supp, interdict=interdict)


@dataclass
class FireSpec:
    id: str
    side: str
    zone: str                  # target zone
    active_from: float
    intensity: float           # 0..1 nominal fire intensity
    crater_rate: float = 0.0   # runway crater fraction per hour at intensity 1


class Fires(Mechanic):
    """Indirect fire on a zone.

    Effective intensity is reduced by the *enemy's* air suppression. It
    supports own units fighting in the zone, raises landing risk for enemy
    aircraft and craters the runway while the firing side does not hold it.
    """
    phase = Phase.FIRES
    name = "fires"

    def __init__(self, fires: list[FireSpec]):
        self.fires = fires

    def step(self, w: World):
        eff: dict[tuple[str, str], float] = {}
        for f in self.fires:
            if w.t < f.active_from:
                continue
            enemy = w.enemy_of(f.side)
            e = f.intensity * (1.0 - w.scratch["suppress"][enemy])
            eff[(f.side, f.zone)] = eff.get((f.side, f.zone), 0.0) + e
            zone = w.zones[f.zone]
            if zone.runway is not None and zone.control != f.side:
                zone.runway.craters = min(1.0, zone.runway.craters + f.crater_rate * e * w.dt)
        w.scratch["fire"] = eff
