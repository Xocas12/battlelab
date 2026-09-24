"""World state.

The world is deliberately board-game shaped: a handful of named zones (areas,
not hexes), units that sit in a zone or off-map, and per-side doctrine/air
parameters. Mechanics read and mutate this state; nothing else does.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .params import stable_hash

INF = math.inf

# unit status values
PENDING, ACTIVE, WITHDRAWN, BROKEN, DESTROYED = (
    "pending", "active", "withdrawn", "broken", "destroyed")


@dataclass
class Morale:
    base_hazard: float = 0.0        # per hour, independent of the fight
    ammo_out_h: float = INF         # hours after first contact when ammo runs out
    withdraw_ratio: float = INF     # leave at once if enemy/own effective > this
    commit_h: float = INF           # counterattacks give up after this long
    on_break: str = "withdraw"      # "withdraw" (retreats off-map) or "disperse"
    # Command decision cycle. decision_h = 0: the unit leaves the fight on its
    # own continuous hazard. decision_h > 0: the fight-or-leave hazard is only
    # evaluated by the commander at decision points every decision_h hours,
    # on a picture that may be missing reports (comms_loss), in which case the
    # commander assumes at least `fog` casualties. night_moves: an order to
    # withdraw is only executed in darkness (enemy air superiority by day).
    decision_h: float = 0.0
    comms_loss: float = 0.0
    fog: float = 0.0
    night_moves: bool = False


@dataclass
class Unit:
    id: str
    side: str
    kind: str
    strength: float
    quality: float = 1.0
    dug_in: float = 1.0             # multiplier when defending
    zone: str | None = None
    posture: str = "defend"         # defend | attack
    status: str = PENDING
    morale: Morale = field(default_factory=Morale)
    initial: float = 0.0
    peak: float = 0.0
    first_contact: float | None = None
    arrived_at: float | None = None
    tags: frozenset = frozenset()

    def activate(self, zone: str, t: float, posture: str):
        self.zone, self.status, self.posture, self.arrived_at = zone, ACTIVE, posture, t
        self.initial = self.initial or self.strength
        self.peak = max(self.peak, self.strength)

    @property
    def active(self) -> bool:
        return self.status == ACTIVE and self.strength > 0


@dataclass
class Runway:
    obstacles: float = 0.0   # removable (vehicles, wrecks): 0..1 blocked fraction
    craters: float = 0.0     # needs engineering repair: 0..1 damaged fraction

    @property
    def usable(self) -> float:
        return max(0.0, min(1.0, (1 - self.obstacles) * (1 - self.craters)))


@dataclass
class Zone:
    id: str
    kind: str = "open"
    defense_mult: float = 1.0
    runway: Runway | None = None
    control: str | None = None       # side id, "contested" or None


@dataclass
class AirPosture:
    """A side's air situation over the battle area."""
    cas: float = 1.0               # combat multiplier for own ground units
    suppress_enemy_fires: float = 0.0   # fraction of enemy fire effect removed
    interdiction: float = 0.0      # fraction of enemy attacking strength removed
    ingress_loss: float = 0.0      # per-aircraft loss probability, insertion
    approach_loss: float = 0.0     # per-aircraft loss probability, air-landing
    night_limited: bool = False    # air effects drop to night_factor at night
    night_factor: float = 0.25


@dataclass
class Side:
    id: str
    role: str                      # attacker | defender
    air: AirPosture = field(default_factory=AirPosture)
    doctrine: dict[str, float] = field(default_factory=dict)


@dataclass
class Event:
    t: float
    kind: str
    data: dict[str, Any]


class World:
    def __init__(self, *, seed: int, run_index: int, dt: float, horizon: float,
                 h_hour_clock: float, params: dict[str, float]):
        self.t = 0.0
        self.dt = dt
        self.horizon = horizon
        self.h_hour_clock = h_hour_clock
        self.params = params
        self.zones: dict[str, Zone] = {}
        self.units: dict[str, Unit] = {}
        self.sides: dict[str, Side] = {}
        self.log: list[Event] = []
        self.metrics: dict[str, Any] = {}
        self.scratch: dict[str, Any] = {}     # per-turn blackboard between phases
        self.persist: dict[str, Any] = {}     # per-run state owned by mechanics
        self._seed, self._run = seed, run_index
        self._rngs: dict[str, np.random.Generator] = {}

    # -- randomness: one independent stream per named component -------------
    def rng(self, stream: str) -> np.random.Generator:
        g = self._rngs.get(stream)
        if g is None:
            ss = np.random.SeedSequence([self._seed, self._run, stable_hash(stream), 0x5EED])
            g = self._rngs[stream] = np.random.default_rng(ss)
        return g

    # -- time ----------------------------------------------------------------
    @property
    def clock(self) -> float:
        return (self.h_hour_clock + self.t) % 24.0

    def is_day(self) -> bool:
        return 6.0 <= self.clock < 20.0

    def air_scale(self, side: str) -> float:
        a = self.sides[side].air
        return 1.0 if (self.is_day() or not a.night_limited) else a.night_factor

    # -- queries -------------------------------------------------------------
    def units_in(self, zone: str, side: str | None = None) -> list[Unit]:
        return [u for u in self.units.values()
                if u.active and u.zone == zone and (side is None or u.side == side)]

    def enemy_of(self, side: str) -> str:
        others = [s for s in self.sides if s != side]
        if len(others) != 1:
            raise ValueError("two-sided scenarios only (for now)")
        return others[0]

    def attacker(self) -> str:
        return next(s.id for s in self.sides.values() if s.role == "attacker")

    def defender(self) -> str:
        return next(s.id for s in self.sides.values() if s.role == "defender")

    # -- logging -------------------------------------------------------------
    def emit(self, kind: str, **data):
        self.log.append(Event(self.t, kind, data))
