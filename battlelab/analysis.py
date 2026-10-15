"""Analysis shared by every backend (native engine or CMO)."""
from __future__ import annotations

import itertools
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
    cols = ["param", "eta2", "direction", "noise_floor"]
    if not rows:          # constant outcome (or nothing sampled): nothing to screen
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows, columns=cols).sort_values(
        "eta2", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Calibration by rejection (approximate Bayesian computation)
# ---------------------------------------------------------------------------
# A parameter counts as constrained by the anchors when any of these holds,
# each clear of Monte Carlo noise (CAL_KS_P, CAL_Z):
# * its posterior differs from its prior by at least CAL_KS_MIN in the
#   Kolmogorov-Smirnov distance (prior-quantile units: 0.2 means a fifth of the
#   prior's mass has moved);
# * its posterior p10-p90 range covers at most CAL_WIDTH of the prior's
#   (measured in prior quantiles, so a narrowing from both sides counts);
# * a region of the prior is down-weighted: a prior quintile (one parameter) or
#   a tercile cell (a pair) accepts at most CAL_DOWN times the overall share.
# The posterior mean alone misses most constraints: cutting the bottom fifth of
# a uniform prior moves its mean by only 0.35 prior SD, and a symmetric
# narrowing does not move it at all.
CAL_KS_MIN = 0.1
CAL_KS_P = 0.001
CAL_WIDTH = 0.85
CAL_DOWN = 0.5
CAL_Z = 3.0
CAL_QUANTILES = 5
CAL_PAIR_TOP = 4
CAL_PAIR_BINS = 3
CAL_STRUCTURAL = 0.3


def abc_mask(df: pd.DataFrame, anchors: list[dict]) -> pd.Series:
    """Runs that reproduce every anchor."""
    keep = pd.Series(True, index=df.index)
    for a in anchors:
        keep &= _anchor_mask(df, a).fillna(False)
    return keep


def _kolmogorov_sf(lam: float) -> float:
    """P(K > lam) for the Kolmogorov distribution (asymptotic KS p-value)."""
    if lam < 0.2:
        return 1.0
    s = sum((-1) ** (k - 1) * math.exp(-2 * k * k * lam * lam) for k in range(1, 101))
    return float(min(1.0, max(0.0, 2 * s)))


def _ks_vs_prior(x: pd.Series, keep: pd.Series) -> tuple[float, float]:
    """KS distance between posterior and prior, and its p-value.

    The distance is max |F_post - F_prior| over the sampled values, so it is in
    prior-quantile units and does not depend on the parameter's scale. Since
    F_prior = acc F_accepted + (1 - acc) F_rejected, it is (1 - acc) times the
    two-sample KS distance between accepted and rejected runs, which gives the
    p-value (asymptotic, with Stephens' correction).
    """
    v = x.to_numpy(float)
    srt = np.sort(v)
    post = np.sort(v[keep.to_numpy(bool)])
    n, m = len(srt), len(post)
    if m == 0 or m == n:
        return 0.0, 1.0
    grid = np.unique(srt)
    d = float(np.max(np.abs(np.searchsorted(post, grid, side="right") / m
                            - np.searchsorted(srt, grid, side="right") / n)))
    ne = m * (n - m) / n
    lam = (math.sqrt(ne) + 0.12 + 0.11 / math.sqrt(ne)) * d / (1 - m / n)
    return d, _kolmogorov_sf(lam)


def _down_weighted(cell_acc: float, cell_n: int, acc: float) -> bool:
    """A region accepting at most CAL_DOWN of the overall share, beyond noise."""
    if cell_n == 0 or not 0 < acc < 1:
        return False
    z = (acc - cell_acc) / math.sqrt(acc * (1 - acc) / cell_n)
    return cell_acc <= CAL_DOWN * acc and z >= CAL_Z


def abc_posterior(df: pd.DataFrame, anchors: list[dict]) -> tuple[pd.DataFrame, float]:
    """Keep the runs that reproduce every anchor; compare parameter
    distributions before (prior) and after (posterior) the filter.

    Per parameter: prior and posterior means and p10/p90; `shift_sd`, the mean
    shift in prior SDs; `sd_ratio`, posterior over prior SD; `ks`, the
    Kolmogorov-Smirnov distance in prior-quantile units, with `ks_p`; `width`,
    the posterior p10-p90 range as a share of the prior's, both measured in
    prior quantiles; and the acceptance in the worst and best prior quintile
    (`acc_q_min` in quintile `q_min`, 1 = lowest values; `acc_q_max`).
    `constrained` marks a parameter the anchors constrain (see CAL_KS_MIN): a
    one-sided cut, a two-sided narrowing or a down-weighted region, not only a
    moved mean. Rows are sorted
    by `ks`. A parameter that is not constrained alone may still be constrained
    jointly with another (`abc_pairs`). Do not reuse the anchors used here as
    independent validation.
    """
    keep = abc_mask(df, anchors)
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
        ks, ks_p = _ks_vs_prior(x, keep)
        q = pd.qcut(x, CAL_QUANTILES, labels=False, duplicates="drop")
        by_q = keep.groupby(q).agg(["mean", "size"])
        worst = by_q["mean"].idxmin()
        down = _down_weighted(float(by_q.loc[worst, "mean"]), int(by_q.loc[worst, "size"]),
                              acc)
        srt = np.sort(x.to_numpy(float))
        pv = post.to_numpy(float)
        u = (np.searchsorted(srt, pv, "left") + np.searchsorted(srt, pv, "right")) / (2 * len(srt))
        width = float(np.quantile(u, 0.9) - np.quantile(u, 0.1)) / 0.8
        width_se = 0.5 * math.sqrt((1 - acc) / len(post))     # random subset of the prior
        narrow = width <= CAL_WIDTH and (1 - width) >= CAL_Z * width_se
        rows.append({"param": col[2:], "prior_mean": x.mean(), "post_mean": post.mean(),
                     "prior_p10": x.quantile(0.1), "prior_p90": x.quantile(0.9),
                     "post_p10": post.quantile(0.1), "post_p90": post.quantile(0.9),
                     "shift_sd": (post.mean() - x.mean()) / sd if sd > 0 else 0.0,
                     "sd_ratio": post.std() / sd if sd > 0 else 1.0,
                     "ks": ks, "ks_p": ks_p, "width": width,
                     "acc_q_min": float(by_q["mean"].min()), "q_min": int(worst) + 1,
                     "acc_q_max": float(by_q["mean"].max()),
                     "constrained": bool((ks >= CAL_KS_MIN and ks_p < CAL_KS_P) or narrow
                                         or down)})
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values("ks", ascending=False, kind="stable").reset_index(drop=True)
    return out, acc


def abc_pairs(df: pd.DataFrame, anchors: list[dict], params: list[str],
              bins: int = CAL_PAIR_BINS) -> pd.DataFrame:
    """Acceptance over a grid of prior quantile bins for each pair of `params`.

    Catches what a per-parameter summary cannot: two parameters that are each
    harmless alone but rule history out together. Per pair: the worst and best
    cell and their acceptance, and `constrained` if the worst cell is
    down-weighted (at most CAL_DOWN of the overall acceptance, beyond noise).
    Cells are named lo/mid/hi for three bins, else by bin number.
    """
    keep = abc_mask(df, anchors)
    acc = float(keep.mean())
    names = ["lo", "mid", "hi"] if bins == 3 else [str(i + 1) for i in range(bins)]
    rows = []
    for a, b in itertools.combinations(params, 2):
        qa = pd.qcut(df[f"p.{a}"], bins, labels=False, duplicates="drop")
        qb = pd.qcut(df[f"p.{b}"], bins, labels=False, duplicates="drop")
        g = keep.groupby([qa, qb]).agg(["mean", "size"])
        lo, hi = g["mean"].idxmin(), g["mean"].idxmax()
        rows.append({"param_a": a, "param_b": b,
                     "cell_min": f"{names[int(lo[0])]}/{names[int(lo[1])]}",
                     "acc_min": float(g.loc[lo, "mean"]), "n_min": int(g.loc[lo, "size"]),
                     "cell_max": f"{names[int(hi[0])]}/{names[int(hi[1])]}",
                     "acc_max": float(g.loc[hi, "mean"]),
                     "constrained": _down_weighted(float(g.loc[lo, "mean"]),
                                                   int(g.loc[lo, "size"]), acc)})
    cols = ["param_a", "param_b", "cell_min", "acc_min", "n_min", "cell_max", "acc_max",
            "constrained"]
    out = pd.DataFrame(rows, columns=cols)
    if len(out):
        out = out.sort_values("acc_min", kind="stable").reset_index(drop=True)
    return out


def calibration_verdict(post: pd.DataFrame, pairs: pd.DataFrame, acc: float,
                        n: int) -> str:
    """One-line reading of `abc_posterior` and `abc_pairs` over `n` runs.

    Constrained means a one-sided cut, a narrowing or a down-weighted region
    (see CAL_KS_MIN), not a moved mean. Poor fit is called structural when no
    parameter or pair is constrained and acceptance is below CAL_STRUCTURAL, or
    when some are but no prior quintile of any parameter lifts acceptance to
    CAL_STRUCTURAL.
    """
    if acc < 0.1:
        return ("history is rare in the model, so the posterior rests on "
                f"{int(round(acc * n))} runs; shifts are what it would take to "
                "make history typical, not evidence")
    cons = post[post.constrained] if len(post) else post
    single = set(cons.param) if len(cons) else set()
    joint = (pairs[pairs.constrained & ~pairs.param_a.isin(single)
                   & ~pairs.param_b.isin(single)] if len(pairs) else pairs)
    best = float(post.acc_q_max.max()) if len(post) else acc
    if len(cons) or len(joint):
        items = [f"`{r.param}` (KS {r.ks:.2f}, p10-p90 width {r.width:.2f}; prior quintile "
                 f"{r.q_min} accepts {r.acc_q_min:.3f})" for r in cons.head(3).itertuples()]
        items += [f"`{r.param_a}` with `{r.param_b}` jointly ({r.cell_min} accepts "
                  f"{r.acc_min:.2f})" for r in joint.head(2).itertuples()]
        out = "the record constrains " + ", ".join(items)
        if best < CAL_STRUCTURAL:
            out += (f", but no prior quintile lifts acceptance above {best:.2f}: poor "
                    "anchor fit is mostly structural, not parametric")
        return out
    if acc < CAL_STRUCTURAL:
        return ("no parameter or pair is constrained: poor anchor fit is structural, "
                "not parametric")
    return "the anchors barely constrain the parameters"


# ---------------------------------------------------------------------------
# Backend comparison (native engine vs CMO, or any two result tables)
# ---------------------------------------------------------------------------
def compare_backends(a: pd.DataFrame, b: pd.DataFrame, rtol: float = 1e-5
                     ) -> tuple[pd.DataFrame, dict]:
    """Compare two result tables run by run.

    Rows are paired on `run`. Shared `p.*` columns must agree (same design,
    same draws); `info["param_mismatch"]` lists the ones that do not. For each
    shared metric: boolean metrics report both shares, the paired difference
    with a 95% interval, agreement and the two discordant counts (a McNemar
    table); numeric metrics report both means, the paired mean difference with
    a 95% interval and the correlation.
    """
    m = a.merge(b, on="run", suffixes=("|a", "|b"))
    info: dict = {"n_a": len(a), "n_b": len(b), "n_paired": len(m), "param_mismatch": []}
    shared_p = sorted(c for c in a.columns if c.startswith("p.") and c in b.columns)
    for c in shared_p:
        x = pd.to_numeric(m[f"{c}|a"], errors="coerce").to_numpy(float)
        y = pd.to_numeric(m[f"{c}|b"], errors="coerce").to_numpy(float)
        if not np.allclose(x, y, rtol=rtol, atol=1e-9, equal_nan=True):
            info["param_mismatch"].append(c[2:])
    info["shared_params"] = len(shared_p)
    rows = []
    for c in sorted(c for c in a.columns if c.startswith("m.") and c in b.columns):
        sa, sb = m[f"{c}|a"], m[f"{c}|b"]
        if sa.dtype == bool or sb.dtype == bool:
            x, y = sa.astype(bool).to_numpy(), sb.astype(bool).to_numpy()
            d = x.astype(float) - y.astype(float)
            se = d.std(ddof=1) / math.sqrt(len(d)) if len(d) > 1 else math.nan
            rows.append({"metric": c[2:], "kind": "share", "a": x.mean(), "b": y.mean(),
                         "diff": d.mean(), "lo95": d.mean() - 1.96 * se,
                         "hi95": d.mean() + 1.96 * se, "agree": float((x == y).mean()),
                         "only_a": int((x & ~y).sum()), "only_b": int((~x & y).sum()),
                         "corr": math.nan, "n": len(d)})
        else:
            x = pd.to_numeric(sa, errors="coerce")
            y = pd.to_numeric(sb, errors="coerce")
            ok = x.notna() & y.notna()
            if ok.sum() < 2:
                continue
            d = (x - y)[ok]
            se = d.std(ddof=1) / math.sqrt(len(d))
            corr = float(np.corrcoef(x[ok], y[ok])[0, 1]) if x[ok].std() > 0 and \
                y[ok].std() > 0 else math.nan
            rows.append({"metric": c[2:], "kind": "mean", "a": x[ok].mean(), "b": y[ok].mean(),
                         "diff": d.mean(), "lo95": d.mean() - 1.96 * se,
                         "hi95": d.mean() + 1.96 * se, "agree": math.nan,
                         "only_a": int((x.notna() & y.isna()).sum()),
                         "only_b": int((x.isna() & y.notna()).sum()), "corr": corr,
                         "n": int(ok.sum())})
    return pd.DataFrame(rows), info


# ---------------------------------------------------------------------------
# Parameter comparison across scenarios
# ---------------------------------------------------------------------------
def _dist_label(prm) -> str:
    d = prm.dist.to_spec()
    kind = d.pop("dist")
    fmt = "{:g}".format
    if kind == "fixed":
        body = fmt(d["value"])
    elif kind == "uniform":
        body = f"{fmt(d['lo'])}-{fmt(d['hi'])}"
    elif kind == "triangular":
        body = f"tri({fmt(d['lo'])}, {fmt(d['mode'])}, {fmt(d['hi'])})"
    else:
        body = f"logn({fmt(d['median'])}, gsd {fmt(d['gsd'])})"
    flag = "A" if prm.prov.assumption else "S"
    if prm.prov.source and prm.prov.assumption:
        flag = "S+A"
    return f"{body} `{flag}{prm.prov.confidence[0]}`"


def parameter_table(scenarios) -> pd.DataFrame:
    """Every parameter of every scenario, side by side, with its factor bundle.

    Cells show the distribution and a provenance flag: S = sourced,
    A = assumption, S+A = sourced fact turned into a number by judgement,
    followed by the confidence initial (l/m/h).
    """
    bundle: dict[str, str] = {}
    for s in scenarios:
        for f, names in s.factors.items():
            for n in names:
                bundle.setdefault(n, f)
    names = sorted({n for s in scenarios for n in s.space.names()},
                   key=lambda n: (bundle.get(n, "~" + n.split(".")[0]), n))
    rows = []
    for n in names:
        row = {"parameter": f"`{n}`", "bundle": bundle.get(n, n.split(".")[0] + " (not swapped)")}
        for s in scenarios:
            row[s.id] = _dist_label(s.space[n]) if n in s.space else "-"
        rows.append(row)
    return pd.DataFrame(rows)
