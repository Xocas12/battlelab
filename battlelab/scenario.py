"""Scenarios are data.

A scenario YAML file declares sources, parameters (distribution + provenance),
sides, zones, units, fires, airlift, mechanic settings, the outcome, historical
anchors and factor bundles. Any value written as "$name" is a reference to a
parameter and is filled in from the sampled parameter set for each run.

`Scenario.lint()` enforces the modelling discipline: every parameter must cite
a source or be flagged as an assumption, every reference must resolve, and
factor bundles must line up across the scenarios they will be swapped between.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .engine import Engine, Mechanic
from .mechanics import (GO_RULES, RESOLVERS, Airlift, AirliftSpec, AirSituation, ArrivalSpec, Arrivals,
                        Combat, Control, Fires, FireSpec, FirstControlTracker, MoraleCheck,
                        Outcome, OutcomeSpec, RunwayEngineering)
from .params import Param, ParamSpace, parse_dist
from .state import AirPosture, Morale, Runway, Side, Unit, World, Zone

KNOWN_METRICS = {
    "landed", "airbridge", "t_airbridge", "t_first_landing", "transports_lost",
    "t_control", "attacker_ever_controls", "attacker_lost_control",
    "attacker_holds_end", "defender_retakes", "runway_end",
    "losses_attacker", "losses_defender",
}
INT_FIELDS = {"aircraft"}


@dataclass
class Issue:
    level: str      # error | warning
    where: str
    message: str

    def __str__(self):
        return f"[{self.level.upper()}] {self.where}: {self.message}"


class ScenarioError(ValueError):
    pass


def _walk_refs(obj, path="") -> list[tuple[str, str]]:
    out = []
    if isinstance(obj, str) and obj.startswith("$"):
        out.append((path, obj[1:]))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out += _walk_refs(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _walk_refs(v, f"{path}[{i}]")
    return out


class Scenario:
    SECTIONS = ("sides", "zones", "units", "fires", "airlift", "mechanics", "outcome")

    def __init__(self, doc: dict, source_text: str = "", path: str | None = None,
                 space: ParamSpace | None = None, variant: dict | None = None):
        self.doc = doc
        self.path = path
        self._text = source_text
        self.id = doc["id"]
        self.title = doc.get("title", self.id)
        self.family = doc.get("family", "generic")
        clock = doc.get("clock", {})
        self.h_hour = float(clock.get("h_hour_local", 0.0))
        self.dt = float(clock.get("dt_h", 0.25))
        self.horizon = float(clock.get("horizon_h", 48.0))
        self.sources = doc.get("sources", {})
        self.space = space or ParamSpace.from_specs(doc.get("parameters", {}))
        self.factors: dict[str, list[str]] = doc.get("factors", {})
        self.anchors: list[dict] = doc.get("anchors", [])
        self.variant = variant or {}

    # -- construction --------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "Scenario":
        text = Path(path).read_text()
        return cls(yaml.safe_load(text), text, str(path))

    def fingerprint(self) -> str:
        h = hashlib.sha256(self._text.encode())
        h.update(json.dumps(self.variant, sort_keys=True, default=str).encode())
        return h.hexdigest()[:16]

    def with_overrides(self, overrides: dict[str, Any]) -> "Scenario":
        """Override parameters: a number fixes it, a dist spec replaces it."""
        space = self.space
        for name, val in overrides.items():
            if name not in space:
                raise ScenarioError(f"{self.id}: unknown parameter {name!r}")
            old = space[name]
            space = space.with_param(name, Param(name, parse_dist(val), old.prov, old.unit))
        v = dict(self.variant)
        v.setdefault("overrides", {}).update({k: str(x) for k, x in overrides.items()})
        return Scenario(self.doc, self._text, self.path, space, v)

    def with_resolver(self, name: str, **kwargs) -> "Scenario":
        """Same scenario, different combat resolver (structural sensitivity)."""
        if name not in RESOLVERS:
            raise ScenarioError(f"unknown resolver {name!r}; have {sorted(RESOLVERS)}")
        doc = copy.deepcopy(self.doc)
        combat = doc.setdefault("mechanics", {}).setdefault("combat", {})
        combat["resolver"] = name
        combat.update(kwargs)
        v = dict(self.variant)
        v["resolver"] = {"name": name, **kwargs}
        return Scenario(doc, self._text, self.path, self.space, v)

    def with_go_rule(self, rule: str) -> "Scenario":
        """Same scenario, different air-landing acceptance rule."""
        if rule not in GO_RULES:
            raise ScenarioError(f"unknown go/no-go rule {rule!r}; have {list(GO_RULES)}")
        doc = copy.deepcopy(self.doc)
        doc.setdefault("mechanics", {}).setdefault("go_no_go", {})["rule"] = rule
        v = dict(self.variant)
        v["go_rule"] = rule
        return Scenario(doc, self._text, self.path, self.space, v)

    def with_params_from(self, other: "Scenario", names: list[str]) -> "Scenario":
        """Take the named parameters (distribution + provenance) from `other`."""
        space = self.space
        for n in names:
            if n not in other.space:
                raise ScenarioError(f"{other.id} has no parameter {n!r}")
            space = space.with_param(n, other.space[n])
        v = dict(self.variant)
        v.setdefault("borrowed", {}).update({n: other.id for n in names})
        return Scenario(self.doc, self._text, self.path, space, v)

    # -- references ----------------------------------------------------------
    def resolve(self, obj, p: dict[str, float], key: str = ""):
        if isinstance(obj, str) and obj.startswith("$"):
            val = p[obj[1:]]
            return int(round(val)) if key in INT_FIELDS else val
        if isinstance(obj, dict):
            return {k: self.resolve(v, p, k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.resolve(v, p, key) for v in obj]
        if key in INT_FIELDS and isinstance(obj, float):
            return int(round(obj))
        return obj

    # -- lint ----------------------------------------------------------------
    def lint(self) -> list[Issue]:
        issues: list[Issue] = []
        refs = []
        for sec in self.SECTIONS:
            refs += _walk_refs(self.doc.get(sec, {}), sec)
        used = {name for _, name in refs}
        for where, name in refs:
            if name not in self.space:
                issues.append(Issue("error", where, f"reference ${name} is not a parameter"))
        for name, prm in self.space.items():
            if name not in used:
                issues.append(Issue("warning", f"parameters.{name}", "never referenced"))
            src = prm.prov.source
            if src is None and not prm.prov.assumption:
                issues.append(Issue("error", f"parameters.{name}",
                                    "needs `source:` or `assumption: true`"))
            if src is not None and src not in self.sources:
                issues.append(Issue("error", f"parameters.{name}", f"unknown source {src!r}"))
        roles = [s.get("role") for s in self.doc.get("sides", {}).values()]
        if sorted(roles) != ["attacker", "defender"]:
            issues.append(Issue("error", "sides", "need exactly one attacker and one defender"))
        zones = set(self.doc.get("zones", {}))
        sides = set(self.doc.get("sides", {}))
        for uid, u in self.doc.get("units", {}).items():
            if u.get("side") not in sides:
                issues.append(Issue("error", f"units.{uid}", f"unknown side {u.get('side')!r}"))
            arr = u.get("arrive")
            if arr and arr.get("zone") not in zones:
                issues.append(Issue("error", f"units.{uid}", f"unknown zone {arr.get('zone')!r}"))
        al = self.doc.get("airlift")
        if al and al.get("unit") not in self.doc.get("units", {}):
            issues.append(Issue("error", "airlift", f"unknown unit {al.get('unit')!r}"))
        for f, names in self.factors.items():
            for n in names:
                if n not in self.space:
                    issues.append(Issue("error", f"factors.{f}", f"unknown parameter {n!r}"))
        for a in self.anchors:
            if a.get("metric") not in KNOWN_METRICS:
                issues.append(Issue("error", f"anchors.{a.get('id')}",
                                    f"unknown metric {a.get('metric')!r}"))
            if a.get("source") and a["source"] not in self.sources:
                issues.append(Issue("error", f"anchors.{a.get('id')}",
                                    f"unknown source {a['source']!r}"))
        return issues

    @staticmethod
    def lint_pair(a: "Scenario", b: "Scenario") -> list[Issue]:
        """Factor bundles must be identical so that swaps are well defined."""
        issues = []
        if a.factors.keys() != b.factors.keys():
            issues.append(Issue("error", "factors", f"{a.id} and {b.id} define different factors"))
        for f in a.factors:
            if sorted(a.factors[f]) != sorted(b.factors.get(f, [])):
                issues.append(Issue("error", f"factors.{f}",
                                    f"parameter lists differ between {a.id} and {b.id}"))
        return issues

    # -- build one run ---------------------------------------------------------
    def build(self, params: dict[str, float], seed: int, run_index: int
              ) -> tuple[World, list[Mechanic]]:
        R = self.resolve
        w = World(seed=seed, run_index=run_index, dt=self.dt, horizon=self.horizon,
                  h_hour_clock=self.h_hour, params=params)
        for sid, s in self.doc["sides"].items():
            air = R(s.get("air", {}), params)
            w.sides[sid] = Side(sid, s["role"], AirPosture(**air),
                                {k: float(v) for k, v in R(s.get("doctrine", {}), params).items()})
        for zid, z in self.doc["zones"].items():
            z = R(z, params)
            rw = Runway(**z["runway"]) if "runway" in z else None
            w.zones[zid] = Zone(zid, z.get("kind", "open"), float(z.get("defense_mult", 1.0)), rw,
                                control=z.get("control"))
        arrivals = []
        for uid, u in self.doc["units"].items():
            u = R(u, params)
            w.units[uid] = Unit(
                id=uid, side=u["side"], kind=u.get("kind", "infantry"),
                strength=float(u.get("strength", 0.0)), quality=float(u.get("quality", 1.0)),
                dug_in=float(u.get("dug_in", 1.0)), morale=Morale(**u.get("morale", {})),
                tags=frozenset(u.get("tags", [])))
            if "arrive" in u:
                arrivals.append(ArrivalSpec(unit_id=uid, **u["arrive"]))
        fires = [FireSpec(**R(f, params)) for f in self.doc.get("fires", [])]
        mcfg = R(self.doc.get("mechanics", {}), params)
        ccfg = dict(mcfg.get("combat", {}))
        resolver_cls = RESOLVERS[ccfg.pop("resolver", "lanchester")]
        rkeys = {"kill_rate"} if resolver_cls.name == "lanchester" else {"round_h"}
        resolver = resolver_cls(**{k: ccfg.pop(k) for k in list(ccfg) if k in rkeys})
        ccfg.pop("kill_rate", None)
        ccfg.pop("round_h", None)
        mechs: list[Mechanic] = [
            Arrivals(arrivals), AirSituation(), Fires(fires),
            Combat(resolver, **ccfg), MoraleCheck(**mcfg.get("morale", {})),
            Control(), FirstControlTracker(), RunwayEngineering(),
            Outcome(OutcomeSpec(**R(self.doc["outcome"], params))),
        ]
        if self.doc.get("airlift"):
            al = R(self.doc["airlift"], params)
            al["unit_id"] = al.pop("unit")
            gng = mcfg.get("go_no_go", {})
            al.update(go_rule=gng.get("rule", "threshold"),
                      go_width=float(gng.get("width", 0.02)),
                      info_lag_h=float(gng.get("info_lag_h", 0.0)))
            mechs.append(Airlift(AirliftSpec(**al)))
        return w, mechs

    def run(self, params: dict[str, float], seed: int, run_index: int,
            trace: bool = False) -> tuple[World, list[dict]]:
        w, mechs = self.build(params, seed, run_index)
        fn = _default_trace if trace else None
        eng = Engine(mechs, trace=fn)
        eng.run(w)
        return w, eng.trace


def _default_trace(w: World) -> dict:
    row = {"t": w.t}
    for z in w.zones.values():
        row[f"control:{z.id}"] = z.control
        if z.runway:
            row[f"runway:{z.id}"] = round(z.runway.usable, 3)
    for s in w.sides:
        row[f"strength:{s}"] = round(sum(u.strength for u in w.units.values()
                                         if u.side == s and u.active), 1)
    row["landed"] = w.metrics.get("landed", 0.0)
    return row


def deepcopy_doc(doc: dict) -> dict:
    return copy.deepcopy(doc)
