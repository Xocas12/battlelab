"""Parameters: distributions + provenance.

Every number that drives a scenario is a `Param`: a distribution plus a record
of where it came from. Sampling goes through the inverse CDF (`ppf`) of a
per-parameter uniform draw, so a parameter's draw depends only on
(seed, run index, parameter name). Changing one parameter's distribution in an
experiment therefore leaves every other parameter's draw untouched - common
random numbers for free.
"""
from __future__ import annotations

import math
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from statistics import NormalDist
from typing import Any

import numpy as np

CONFIDENCE_LEVELS = ("low", "medium", "high")


class ParamError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------
class Dist:
    kind = "abstract"

    def ppf(self, u: float) -> float:
        raise NotImplementedError

    def bounds(self) -> tuple[float, float]:
        raise NotImplementedError

    def mean(self) -> float:
        raise NotImplementedError

    def to_spec(self) -> dict:
        raise NotImplementedError


@dataclass(frozen=True)
class Fixed(Dist):
    value: float
    kind = "fixed"

    def ppf(self, u):
        return self.value

    def bounds(self):
        return (self.value, self.value)

    def mean(self):
        return self.value

    def to_spec(self):
        return {"dist": "fixed", "value": self.value}


@dataclass(frozen=True)
class Uniform(Dist):
    lo: float
    hi: float
    kind = "uniform"

    def __post_init__(self):
        if self.hi < self.lo:
            raise ParamError(f"uniform hi < lo ({self.lo}, {self.hi})")

    def ppf(self, u):
        return self.lo + (self.hi - self.lo) * u

    def bounds(self):
        return (self.lo, self.hi)

    def mean(self):
        return 0.5 * (self.lo + self.hi)

    def to_spec(self):
        return {"dist": "uniform", "lo": self.lo, "hi": self.hi}


@dataclass(frozen=True)
class Triangular(Dist):
    lo: float
    mode: float
    hi: float
    kind = "triangular"

    def __post_init__(self):
        if not (self.lo <= self.mode <= self.hi) or self.lo == self.hi:
            raise ParamError(f"triangular needs lo <= mode <= hi, lo < hi: {self}")

    def ppf(self, u):
        a, c, b = self.lo, self.mode, self.hi
        fc = (c - a) / (b - a)
        if u < fc:
            return a + math.sqrt(u * (b - a) * (c - a))
        return b - math.sqrt((1 - u) * (b - a) * (b - c))

    def bounds(self):
        return (self.lo, self.hi)

    def mean(self):
        return (self.lo + self.mode + self.hi) / 3.0

    def to_spec(self):
        return {"dist": "triangular", "lo": self.lo, "mode": self.mode, "hi": self.hi}


@dataclass(frozen=True)
class LogNormal(Dist):
    """Parameterised by median and geometric standard deviation (gsd > 1)."""
    median: float
    gsd: float
    kind = "lognormal"

    def __post_init__(self):
        if self.median <= 0 or self.gsd <= 1:
            raise ParamError("lognormal needs median > 0 and gsd > 1")

    def ppf(self, u):
        u = min(max(u, 1e-12), 1 - 1e-12)
        return self.median * self.gsd ** NormalDist().inv_cdf(u)

    def bounds(self):
        return (self.ppf(0.001), self.ppf(0.999))

    def mean(self):
        s = math.log(self.gsd)
        return self.median * math.exp(0.5 * s * s)

    def to_spec(self):
        return {"dist": "lognormal", "median": self.median, "gsd": self.gsd}


def parse_dist(spec: Any) -> Dist:
    """Accepts a number (fixed), [lo, hi] (uniform), or a dict with 'dist'."""
    if isinstance(spec, (int, float)):
        return Fixed(float(spec))
    if isinstance(spec, (list, tuple)) and len(spec) == 2:
        return Uniform(float(spec[0]), float(spec[1]))
    if not isinstance(spec, Mapping) or "dist" not in spec:
        raise ParamError(f"cannot parse distribution from {spec!r}")
    kind = spec["dist"]
    if kind == "fixed":
        return Fixed(float(spec["value"]))
    if kind == "uniform":
        return Uniform(float(spec["lo"]), float(spec["hi"]))
    if kind == "triangular":
        return Triangular(float(spec["lo"]), float(spec["mode"]), float(spec["hi"]))
    if kind == "lognormal":
        return LogNormal(float(spec["median"]), float(spec["gsd"]))
    raise ParamError(f"unknown distribution {kind!r}")


# ---------------------------------------------------------------------------
# Provenance and parameters
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Provenance:
    source: str | None = None      # key into the scenario's `sources` block
    note: str = ""
    confidence: str = "low"
    assumption: bool = False       # True = judgement call, no direct source

    def __post_init__(self):
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ParamError(f"confidence must be one of {CONFIDENCE_LEVELS}")


@dataclass(frozen=True)
class Param:
    name: str
    dist: Dist
    prov: Provenance = field(default_factory=Provenance)
    unit: str = ""

    @classmethod
    def from_spec(cls, name: str, spec: Any) -> Param:
        if isinstance(spec, Mapping):
            dist = parse_dist(spec)
            prov = Provenance(source=spec.get("source"), note=spec.get("note", ""),
                              confidence=spec.get("confidence", "low"),
                              assumption=bool(spec.get("assumption", False)))
            return cls(name, dist, prov, spec.get("unit", ""))
        return cls(name, parse_dist(spec))


def stable_hash(name: str) -> int:
    return zlib.crc32(name.encode("utf-8")) & 0x7FFFFFFF


def param_uniform(seed: int, run_index: int, name: str) -> float:
    """The CRN draw for one parameter in one run."""
    ss = np.random.SeedSequence([seed, run_index, stable_hash(name), 0xBA77])
    return float(np.random.default_rng(ss).random())


class ParamSpace:
    """An ordered collection of named parameters."""

    def __init__(self, params: Mapping[str, Param]):
        self._p = dict(params)

    @classmethod
    def from_specs(cls, specs: Mapping[str, Any]) -> ParamSpace:
        return cls({k: Param.from_spec(k, v) for k, v in specs.items()})

    def __contains__(self, name):
        return name in self._p

    def __getitem__(self, name) -> Param:
        return self._p[name]

    def __iter__(self):
        return iter(self._p)

    def names(self) -> list[str]:
        return list(self._p)

    def items(self):
        return self._p.items()

    def with_param(self, name: str, param: Param) -> ParamSpace:
        new = dict(self._p)
        new[name] = replace(param, name=name)
        return ParamSpace(new)

    def with_value(self, name: str, value: float) -> ParamSpace:
        if name not in self._p:
            raise ParamError(f"unknown parameter {name!r}")
        old = self._p[name]
        return self.with_param(name, replace(old, dist=Fixed(float(value))))

    def sample(self, seed: int, run_index: int) -> dict[str, float]:
        return {n: p.dist.ppf(param_uniform(seed, run_index, n)) for n, p in self._p.items()}

    def means(self) -> dict[str, float]:
        return {n: p.dist.mean() for n, p in self._p.items()}
