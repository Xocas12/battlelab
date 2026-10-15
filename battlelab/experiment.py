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


CONTEXT = "CONTEXT"


def context_params(home: Scenario, away: Scenario) -> tuple[list[str], list[str]]:
    """Context parameters (`ctx.*`) the two scenarios share, and those only one has.
    Only shared ones can be swapped; structure (zones, wave lists, units) never is."""
    a = {n for n in home.space if n.startswith("ctx.")}
    b = {n for n in away.space if n.startswith("ctx.")}
    return sorted(a & b), sorted(a ^ b)


def variant(home: Scenario, away: Scenario, factors: list[str], mask: tuple,
            groups: dict[str, list[str]] | None = None) -> Scenario:
    groups = groups or home.factors
    names = [n for f, b in zip(factors, mask) if b for n in groups[f]]
    return home.with_params_from(away, names) if names else home


def factor_swap(home: Scenario, away: Scenario, n: int, seed: int = 1,
                factors: list[str] | None = None, outcome: str = "airbridge",
                workers: int = 1, progress: bool = False,
                context: bool = False) -> SwapResult:
    """Full-factorial swap of factor bundles from `away` into `home`. With
    `context`, the shared `ctx.*` parameters form one more bundle, CONTEXT, which
    ordinary swaps leave alone by design (MODELING_STANDARDS §5)."""
    issues = Scenario.lint_pair(home, away)
    if issues:
        raise ValueError("; ".join(map(str, issues)))
    factors = list(factors or home.factors)
    groups = dict(home.factors)
    if context:
        shared, _ = context_params(home, away)
        if not shared:
            raise ValueError(f"{home.id} and {away.id} share no ctx.* parameters")
        groups[CONTEXT] = shared
        factors.append(CONTEXT)
    res = SwapResult(home.id, away.id, factors, outcome)
    masks = list(itertools.product([0, 1], repeat=len(factors)))
    variants = [variant(home, away, factors, m, groups) for m in masks]
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


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------
def _runs_changed(a: pd.DataFrame, b: pd.DataFrame) -> int:
    """Runs (same index, same seed) whose metrics differ anywhere; NaN equals NaN."""
    cols = [c for c in a.columns if c.startswith("m.")]
    x, y = a[cols], b[cols]
    differ = (x != y) & ~(x.isna() & y.isna())
    return int(differ.any(axis=1).sum())


def liveness(scenario: Scenario, n: int, seed: int = 1, workers: int = 1,
             params: list[str] | None = None,
             screen_n: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Which declared parameters and anchors can do anything inside the prior box.

    Each sampled (non-fixed) parameter is pinned at the low and then the high end
    of its range, every other draw unchanged (CRN), and the two batches are
    compared run by run on every metric. A parameter with `runs_changed` 0 changed
    none of runs 0..n-1 across its range. Runs 0..screen_n-1 are compared first,
    and only a parameter that changed none of them is run on to n, so `runs_changed`
    of a live parameter counts within its first `n_compared` runs; the verdict
    (zero or not over n runs) is the same as comparing all n.

    An anchor is checked over the plain batch (n runs) and every end-of-range
    batch; `failing_runs` 0 means it held in all of them, so nothing in the prior
    box makes it fail and it cannot discriminate between runs.

    Returns (parameters: param, lo, hi, runs_changed, n_compared;
             anchors: anchor, failing_runs, variants_failing, variants).
    """
    from .analysis import anchor_holds  # analysis imports this module

    ends = []
    for k, p in scenario.space.items():
        lo, hi = p.dist.bounds()
        if lo < hi and (params is None or k in params):
            ends.append((k, lo, hi))
    pins = [(scenario.with_overrides({k: lo}), scenario.with_overrides({k: hi}))
            for k, lo, hi in ends]
    m = min(n, max(1, screen_n))

    def batches(scs: list[Scenario], count: int, start: int) -> list[pd.DataFrame]:
        if workers > 1:
            with ProcessPoolExecutor(workers) as ex:
                return run_batches(scs, count, seed, workers, keep_params=False,
                                   start=start, executor=ex)
        return run_batches(scs, count, seed, keep_params=False, start=start)

    base = batches([scenario], n, 0)[0]
    first = batches([v for pair in pins for v in pair], m, 0)
    runs = [(first[2 * i], first[2 * i + 1]) for i in range(len(ends))]
    changed = [_runs_changed(a, b) for a, b in runs]
    again = [i for i, c in enumerate(changed) if c == 0] if n > m else []
    if again:
        rest = batches([v for i in again for v in pins[i]], n - m, m)
        for j, i in enumerate(again):
            a, b = rest[2 * j], rest[2 * j + 1]
            changed[i] = _runs_changed(a, b)
            runs[i] = (pd.concat([runs[i][0], a], ignore_index=True),
                       pd.concat([runs[i][1], b], ignore_index=True))
    prow = [{"param": k, "lo": lo, "hi": hi, "runs_changed": changed[i],
             "n_compared": len(runs[i][0])} for i, (k, lo, hi) in enumerate(ends)]
    dfs = [base] + [df for pair in runs for df in pair]
    arow = []
    for a in scenario.anchors:
        fails = [int((~anchor_holds(df, a)).sum()) for df in dfs]
        arow.append({"anchor": a["id"], "failing_runs": sum(fails),
                     "variants_failing": sum(f > 0 for f in fails), "variants": len(dfs)})
    return (pd.DataFrame(prow, columns=["param", "lo", "hi", "runs_changed", "n_compared"]),
            pd.DataFrame(arow, columns=["anchor", "failing_runs", "variants_failing",
                                        "variants"]))


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
