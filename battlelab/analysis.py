"""Analysis shared by every backend (native engine or CMO)."""
from __future__ import annotations

import math
import operator

import numpy as np
import pandas as pd

from .experiment import SwapResult


# ---------------------------------------------------------------------------
# Proportions
# ---------------------------------------------------------------------------
def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Mean / CI for boolean metrics, quantiles for numeric metrics."""
    rows = []
    for col in [c for c in df.columns if c.startswith("m.")]:
        s = df[col]
        if s.dtype == bool:
            v = s.astype(float)
            lo, hi = wilson(v.sum(), len(v))
            rows.append({"metric": col[2:], "kind": "share", "value": v.mean(),
                         "lo95": lo, "hi95": hi, "n": len(v)})
        else:
            v = pd.to_numeric(s, errors="coerce").dropna()
            if len(v) == 0:
                continue
            q = v.quantile([0.1, 0.5, 0.9])
            rows.append({"metric": col[2:], "kind": "median[p10,p90]", "value": q[0.5],
                         "lo95": q[0.1], "hi95": q[0.9], "n": len(v)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Shapley decomposition of a factor-swap experiment
# ---------------------------------------------------------------------------
def shapley(values: dict[tuple, float], k: int) -> np.ndarray:
    """Exact Shapley values of a game over k binary factors.

    values[mask] is the outcome with the factors in `mask` swapped. The result
    satisfies efficiency: sum(phi) == values[all ones] - values[all zeros].
    """
    phi = np.zeros(k)
    fk = math.factorial(k)
    for mask, v in values.items():
        size = sum(mask)
        for i in range(k):
            if mask[i]:
                continue
            with_i = mask[:i] + (1,) + mask[i + 1:]
            w = math.factorial(size) * math.factorial(k - size - 1) / fk
            phi[i] += w * (values[with_i] - v)
    return phi


def shapley_table(res: SwapResult, boot: int = 400, seed: int = 0) -> pd.DataFrame:
    """Shapley values with bootstrap intervals over runs.

    The intervals only reflect Monte Carlo noise given the parameter
    distributions; they say nothing about whether those distributions are right.
    """
    k = len(res.factors)
    keys = list(res.runs)
    point = shapley({m: res.runs[m].mean() for m in keys}, k)
    arr = np.stack([res.runs[m] for m in keys])
    n = arr.shape[1]
    rng = np.random.default_rng(seed)
    draws = np.empty((boot, k))
    for b in range(boot):
        idx = rng.integers(0, n, n)
        means = arr[:, idx].mean(axis=1)
        draws[b] = shapley(dict(zip(keys, means)), k)
    lo, hi = np.quantile(draws, [0.05, 0.95], axis=0)
    single = [res.value(tuple(int(j == i) for j in range(k))) for i in range(k)]
    return pd.DataFrame({"factor": res.factors, "shapley": point, "lo90": lo, "hi90": hi,
                         "single_swap_p": single}).sort_values(
        "shapley", key=np.abs, ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Historical anchors (pattern-oriented validation)
# ---------------------------------------------------------------------------
_OPS = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt, "le": operator.le,
        "gt": operator.gt, "ge": operator.ge}


def _anchor_mask(df: pd.DataFrame, a: dict) -> pd.Series:
    col = f"m.{a['metric']}"
    s = df[col]
    if a["op"] == "between":
        lo, hi = a["value"]
        v = pd.to_numeric(s, errors="coerce")
        return (v >= lo) & (v <= hi)
    if isinstance(a["value"], bool):
        return s.astype(bool) == a["value"]
    return _OPS[a["op"]](pd.to_numeric(s, errors="coerce"), a["value"])


def check_anchors(df: pd.DataFrame, anchors: list[dict]) -> pd.DataFrame:
    """Share of runs reproducing each historical fact, and all of them jointly.

    A model is not "validated" by a high joint share; but a very low share for
    an anchor means the model treats what actually happened as a fluke, which
    is a red flag worth investigating before trusting any counterfactual.
    """
    rows, joint = [], pd.Series(True, index=df.index)
    for a in anchors:
        m = _anchor_mask(df, a).fillna(False)
        joint &= m
        lo, hi = wilson(m.sum(), len(m))
        rows.append({"anchor": a["id"], "metric": a["metric"], "op": a["op"],
                     "target": a["value"], "share": m.mean(), "lo95": lo, "hi95": hi,
                     "source": a.get("source", "")})
    lo, hi = wilson(joint.sum(), len(joint))
    rows.append({"anchor": "ALL (joint)", "metric": "", "op": "", "target": "",
                 "share": joint.mean(), "lo95": lo, "hi95": hi, "source": ""})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Parameter screening
# ---------------------------------------------------------------------------
def screen(df: pd.DataFrame, metric: str = "airbridge", bins: int = 10) -> pd.DataFrame:
    """First-order variance share of each sampled parameter (binned eta^2).

    Cheap screening from a plain Monte Carlo batch: for each parameter, how much
    of the outcome variance is explained by knowing that parameter alone. Fixed
    parameters are skipped. Use it to decide what to pin down next.
    """
    y = df[f"m.{metric}"].astype(float)
    var = y.var()
    rows = []
    for col in [c for c in df.columns if c.startswith("p.")]:
        x = df[col]
        if x.nunique() < 3 or var == 0:
            continue
        q = pd.qcut(x, bins, duplicates="drop")
        eta2 = y.groupby(q, observed=True).mean().var(ddof=0) / var
        corr = np.corrcoef(x, y)[0, 1]
        rows.append({"param": col[2:], "eta2": eta2, "direction": np.sign(corr),
                     "noise_floor": (q.cat.categories.size - 1) / len(y)})
    return pd.DataFrame(rows).sort_values("eta2", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Calibration by rejection (approximate Bayesian computation)
# ---------------------------------------------------------------------------
def abc_posterior(df: pd.DataFrame, anchors: list[dict]) -> tuple[pd.DataFrame, float]:
    """Keep the runs that reproduce every anchor; compare parameter
    distributions before (prior) and after (posterior) the filter.

    A parameter whose posterior moves far from its prior is one the historical
    record actually constrains. Parameters that do not move are not identified
    by these anchors - no amount of fitting will pin them down. Do not reuse
    the anchors used here as independent validation.
    """
    keep = pd.Series(True, index=df.index)
    for a in anchors:
        keep &= _anchor_mask(df, a).fillna(False)
    acc = float(keep.mean())
    rows = []
    for col in [c for c in df.columns if c.startswith("p.")]:
        x = df[col]
        if x.nunique() < 3:
            continue
        post = x[keep]
        if len(post) < 2:
            continue
        sd = x.std()
        rows.append({"param": col[2:], "prior_mean": x.mean(), "post_mean": post.mean(),
                     "post_p10": post.quantile(0.1), "post_p90": post.quantile(0.9),
                     "shift_sd": (post.mean() - x.mean()) / sd if sd > 0 else 0.0})
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values("shift_sd", key=np.abs, ascending=False).reset_index(drop=True)
    return out, acc
