"""Experiments: batches, cross-scenario factor swaps and parameter sweeps.

Everything returns tidy pandas DataFrames: one row per run, parameter columns
prefixed `p.` and metric columns prefixed `m.`. Every saved result gets a
manifest (scenario fingerprints, seeds, overrides, framework version) so a
number in a figure can always be traced back to the exact configuration.
"""
from __future__ import annotations

import itertools
import json
import os
import platform
import time
from concurrent.futures import Executor, ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .scenario import Scenario


# ---------------------------------------------------------------------------
# Single batch
# ---------------------------------------------------------------------------
def _run_chunk(args) -> list[dict]:
    scenario, seed, indices, keep_params = args
    rows = []
    for i in indices:
        p = scenario.space.sample(seed, i)
        w, _ = scenario.run(p, seed, i)
        row = {"run": i}
        if keep_params:
            row.update({f"p.{k}": v for k, v in p.items()})
        row.update({f"m.{k}": v for k, v in w.metrics.items()})
        rows.append(row)
    return rows


def run_batch(scenario: Scenario, n: int, seed: int = 1, workers: int = 1,
              keep_params: bool = True, start: int = 0,
              executor: Executor | None = None) -> pd.DataFrame:
    """One row per run. Pass `executor` to reuse a process pool across batches."""
    return run_batches([scenario], n, seed, workers, keep_params, start, executor)[0]


def run_batches(scenarios: list[Scenario], n: int, seed: int = 1, workers: int = 1,
                keep_params: bool = True, start: int = 0,
                executor: Executor | None = None) -> list[pd.DataFrame]:
    """Several batches (same seeds and run indices) through one process pool."""
    idx = list(range(start, start + n))
    if workers <= 1 and executor is None:
        parts = [_run_chunk((sc, seed, idx, keep_params)) for sc in scenarios]
    else:
        k = max(workers, 1)
        chunks = [idx[j::k] for j in range(k) if idx[j::k]]
        jobs = [(i, (sc, seed, c, keep_params)) for i, sc in enumerate(scenarios) for c in chunks]
        own = executor is None
        ex = executor or ProcessPoolExecutor(k)
        try:
            futs = [(i, ex.submit(_run_chunk, job)) for i, job in jobs]
            parts = [[] for _ in scenarios]
            for i, f in futs:
                parts[i].extend(f.result())
        finally:
            if own:
                ex.shutdown()
        for rows in parts:
            rows.sort(key=lambda r: r["run"])
    out = []
    for sc, rows in zip(scenarios, parts):
        df = pd.DataFrame(rows)
        df.attrs["scenario"] = sc.id
        df.attrs["fingerprint"] = sc.fingerprint()
        df.attrs["seed"] = seed
        out.append(df)
    return out


# ---------------------------------------------------------------------------
# Cross-scenario factor swap (full factorial over factor bundles)
# ---------------------------------------------------------------------------
@dataclass
class SwapResult:
    home: str
    away: str
    factors: list[str]
    outcome: str
    runs: dict[tuple, np.ndarray] = field(default_factory=dict)   # mask -> per-run 0/1

    def table(self) -> pd.DataFrame:
        rows = []
        for mask, v in self.runs.items():
            rows.append({**{f: b for f, b in zip(self.factors, mask)},
                         "n_swapped": sum(mask), "p": float(v.mean()), "n": len(v)})
        return pd.DataFrame(rows).sort_values(["n_swapped"] + self.factors).reset_index(drop=True)

    def value(self, mask: tuple) -> float:
        return float(self.runs[mask].mean())


def variant(home: Scenario, away: Scenario, factors: list[str], mask: tuple) -> Scenario:
    names = [n for f, b in zip(factors, mask) if b for n in home.factors[f]]
    return home.with_params_from(away, names) if names else home


def factor_swap(home: Scenario, away: Scenario, n: int, seed: int = 1,
                factors: list[str] | None = None, outcome: str = "airbridge",
                workers: int = 1, progress: bool = False) -> SwapResult:
    issues = Scenario.lint_pair(home, away)
    if issues:
        raise ValueError("; ".join(map(str, issues)))
    factors = factors or list(home.factors)
    res = SwapResult(home.id, away.id, factors, outcome)
    masks = list(itertools.product([0, 1], repeat=len(factors)))
    variants = [variant(home, away, factors, m) for m in masks]
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            dfs = run_batches(variants, n, seed, workers, keep_params=False, executor=ex)
    else:
        dfs = []
        for k, v in enumerate(variants):
            dfs.append(run_batch(v, n, seed, keep_params=False))
            if progress:
                print(f"  [{k + 1}/{len(masks)}] {home.id} swap={masks[k]} "
                      f"P({outcome})={dfs[-1][f'm.{outcome}'].mean():.3f}", flush=True)
    for mask, df in zip(masks, dfs):
        res.runs[mask] = df[f"m.{outcome}"].astype(float).to_numpy()
    return res


# ---------------------------------------------------------------------------
# Sweeps
# ---------------------------------------------------------------------------
def sweep(scenario: Scenario, grid: dict[str, list[float]], n: int, seed: int = 1,
          outcome: str = "airbridge", workers: int = 1) -> pd.DataFrame:
    names = list(grid)
    points = list(itertools.product(*(grid[k] for k in names)))
    variants = [scenario.with_overrides(dict(zip(names, vals))) for vals in points]
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            dfs = run_batches(variants, n, seed, workers, keep_params=False, executor=ex)
    else:
        dfs = [run_batch(v, n, seed, keep_params=False) for v in variants]
    rows = []
    for vals, df in zip(points, dfs):
        v = df[f"m.{outcome}"].astype(float)
        rows.append({**dict(zip(names, vals)), "p": v.mean(), "n": len(v)})
    return pd.DataFrame(rows)


def parse_grid(spec: str) -> tuple[str, list[float]]:
    """'name=lo:hi:steps' or 'name=a,b,c'."""
    name, rng = spec.split("=", 1)
    if ":" in rng:
        lo, hi, k = rng.split(":")
        return name, list(np.linspace(float(lo), float(hi), int(k)))
    return name, [float(x) for x in rng.split(",")]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def manifest(**extra) -> dict:
    m = {"framework": "battlelab", "version": __version__,
         "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "python": platform.python_version(), "numpy": np.__version__}
    m.update(extra)
    return m


def save(df: pd.DataFrame, out_dir: str | Path, name: str, meta: dict) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.csv"
    df.to_csv(path, index=False)
    (out / f"{name}.manifest.json").write_text(json.dumps(manifest(**meta), indent=2,
                                                          default=str))
    return path


def cpu_workers() -> int:
    return max(1, (os.cpu_count() or 1) - 1)
