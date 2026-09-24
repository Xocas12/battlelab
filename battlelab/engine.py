"""The engine: a board-game turn sequence.

Each turn (dt hours) runs every mechanic in phase order. Mechanics are small
classes that declare which phase they belong to and which parameters they
read; the scenario loader checks those declarations before anything runs.
"""
from __future__ import annotations

from enum import IntEnum
from typing import Callable, Iterable

from .state import World


class Phase(IntEnum):
    SCHEDULE = 0      # arrivals, activations
    AIR = 10          # air situation for the turn
    FIRES = 20        # artillery / bombardment, runway cratering
    COMBAT = 30       # attrition in contested zones
    MORALE = 40       # withdraw / break decisions
    CONTROL = 50      # zone control
    ENGINEERING = 60  # clearance, demolition
    AIRLIFT = 70      # air-landing decisions and landings
    RECORD = 90       # metrics, traces


class Mechanic:
    phase: Phase = Phase.RECORD
    name: str = "mechanic"

    def setup(self, world: World) -> None:
        """Called once after the world is built, before turn 0."""

    def step(self, world: World) -> None:
        raise NotImplementedError

    def finalize(self, world: World) -> None:
        """Called once after the last turn (write metrics here)."""


class Engine:
    def __init__(self, mechanics: Iterable[Mechanic],
                 trace: Callable[[World], dict] | None = None):
        self.mechanics = sorted(mechanics, key=lambda m: m.phase)
        self.trace_fn = trace
        self.trace: list[dict] = []

    def run(self, world: World) -> World:
        for m in self.mechanics:
            m.setup(world)
        n_steps = int(round(world.horizon / world.dt))
        for step in range(n_steps + 1):
            world.t = step * world.dt
            world.scratch = {}
            for m in self.mechanics:
                m.step(world)
            if self.trace_fn is not None:
                self.trace.append(self.trace_fn(world))
        for m in self.mechanics:
            m.finalize(world)
        return world
