"""`battlelab report`: run the standard pipeline and write results/SUMMARY.md.

Every number in the summary is computed here from files saved next to it
(each with a manifest), so the document cannot drift from the results. The
statements it makes are mechanical (largest contributions, sign agreement
across resolvers, parameters the anchors constrain); interpretation stays in
the changelog and in the reader's head.
"""
from __future__ import annotations

import itertools
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import __version__, analysis, experiment
from .mechanics.combat import expected_loss_rates
from .scenario import Scenario

RESOLVER_NAMES = ("lanchester", "crt")


@dataclass
class ReportConfig:
    scenarios: list[str]
    n: int = 1000
    seed: int = 1
    workers: int = 1
    out: str = "results"
    sweep_scenario: str | None = None           # id of the scenario to sweep
    sweep_grid: dict[str, list[float]] = field(default_factory=lambda: {
        "risk.tolerance": list(np.linspace(0, 0.4, 9)),
        "denial.t_fires": list(np.linspace(1, 12, 12))})
    go_rule_pair: tuple[str, str] | None = None  # ids for the go/no-go comparison
    factors: list[str] | None = None             # swap only these bundles (default: all)
    pairs: list[tuple[str, str]] | None = None   # swap only these (both directions); None = all
    context_pairs: list[tuple[str, str]] = field(default_factory=list)  # 3b: + CONTEXT bundle
    # one-parameter sweeps: (tag, scenario id, parameter, values, fixed overrides)
    line_sweeps: list[tuple[str, str, str, list[float], dict]] = field(default_factory=list)
    log: bool = True


def _say(cfg: ReportConfig, msg: str):
    if cfg.log:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _f(x, nd=2) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    if isinstance(x, (bool, np.bool_)):
        return str(bool(x)).lower()
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    if isinstance(x, (float, np.floating)):
        return f"{x:+.{nd}f}" if nd and x < 0 else f"{x:.{nd}f}"
    return str(x)


def md_table(df: pd.DataFrame, nd: int = 2) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(_f(r[c], nd) for c in cols) + " |")
    return "\n".join(lines)


def _variant(s: Scenario, resolver: str | None = None, go_rule: str | None = None,
             overrides: dict | None = None) -> Scenario:
    if resolver:
        s = s.with_resolver(resolver)
    if go_rule:
        s = s.with_go_rule(go_rule)
    if overrides:
        s = s.with_overrides(overrides)
    return s


def run_report(cfg: ReportConfig) -> Path:
    out = Path(cfg.out)
    out.mkdir(parents=True, exist_ok=True)
    scen = [Scenario.load(p) for p in cfg.scenarios]
    for s in scen:
        errs = [i for i in s.lint() if i.level == "error"]
        if errs:
            raise SystemExit(f"{s.path}: {len(errs)} lint errors; run `battlelab lint`")
    for s1, s2 in itertools.combinations(scen, 2):
        if s1.family == s2.family and Scenario.lint_pair(s1, s2):
            raise SystemExit(f"factor bundles of {s1.id} and {s2.id} differ")
    by_id = {s.id: s for s in scen}
    N, seed, W = cfg.n, cfg.seed, cfg.workers
    sec: list[str] = []
    values: dict[str, float] = {}      # {{key}} placeholders for results/NOTES.md
    t0 = time.time()

    # 1. anchors ----------------------------------------------------------------
    _say(cfg, "anchors")
    anchor_tabs: dict[tuple[str, str], pd.DataFrame] = {}
    for s in scen:
        for r in RESOLVER_NAMES:
            v = _variant(s, r)
            df = experiment.run_batch(v, 2 * N, seed, W)
            t = analysis.check_anchors(df, s.anchors)
            anchor_tabs[(s.id, r)] = t
            for _, row in t.iterrows():
                key = "joint" if row["anchor"] == "ALL (joint)" else row["anchor"]
                values[f"anchor.{s.id}.{r}.{key}"] = float(row["share"])
            experiment.save(t, out, f"anchors_{s.id}_{r}",
                            {"scenario": v.fingerprint(), "n": 2 * N, "seed": seed,
                             "variant": v.variant})
    rows = []
    for s in scen:
        for aid in [x["id"] for x in s.anchors] + ["ALL (joint)"]:
            row = {"scenario": s.id, "anchor": aid}
            for r in RESOLVER_NAMES:
                t = anchor_tabs[(s.id, r)].set_index("anchor")
                row[r] = t.loc[aid, "share"]
            rows.append(row)
    anchors_df = pd.DataFrame(rows)
    sec.append("## 1. Is history a typical outcome in the model?\n\n"
               f"Share of runs reproducing each historical fact (n = {2 * N:,} per scenario "
               "per resolver; files `anchors_*.csv`). A low share means the model treats what "
               "happened as unusual; a high share does not validate it.\n\n"
               + md_table(anchors_df))

    # 2. calibration and screening ----------------------------------------------
    _say(cfg, "calibration and screening")
    cal_lines, scr_lines = [], []
    for s in scen:
        df = experiment.run_batch(s, 6 * N, seed, W)
        post, acc = analysis.abc_posterior(df, s.anchors)
        experiment.save(post, out, f"calibrate_{s.id}",
                        {"scenario": s.fingerprint(), "n": 6 * N, "seed": seed,
                         "acceptance": acc})
        top = post.head(3)
        moved = ", ".join(f"`{r.param}` {r.shift_sd:+.2f}" for r in top.itertuples())
        mx = float(post.shift_sd.abs().max()) if len(post) else float("nan")
        verdict = ("history is rare in the model, so the posterior rests on "
                   f"{int(round(acc * len(df)))} runs; shifts are what it would take to "
                   "make history typical, not evidence" if acc < 0.1 else
                   "the record constrains some parameters" if mx >= 0.5 else
                   "no parameter moves by half a prior SD: poor anchor fit is structural, "
                   "not parametric" if acc < 0.3 else
                   "the anchors barely constrain the parameters")
        cal_lines.append(f"* **{s.id}**: acceptance {acc:.3f}; largest shifts (prior SD) "
                         f"{moved}; {verdict}.")
        scr = analysis.screen(df.head(4 * N))      # runs 0..4N-1: the same as a 4N batch
        experiment.save(scr, out, f"screen_{s.id}_airbridge",
                        {"scenario": s.fingerprint(), "n": 4 * N, "seed": seed})
        floor = float(scr.noise_floor.max()) if len(scr) else float("nan")
        above = scr[scr.eta2 > 2 * floor].head(5)
        items = ", ".join(f"`{r.param}` {r.eta2:.2f}" for r in above.itertuples()) or "none"
        flagged = [r.param for r in above.itertuples() if s.space[r.param].prov.assumption
                   or s.space[r.param].prov.confidence == "low"]
        scr_lines.append(f"* **{s.id}**: {items} (noise floor ~{floor:.3f})."
                         + (f" Low-confidence or assumed: {', '.join(f'`{p}`' for p in flagged)}."
                            if flagged else ""))
    n_ass = ", ".join(f"{s.id} {sum(p.prov.assumption for _, p in s.space.items())} of "
                      f"{len(s.space.names())}" for s in scen)
    sec.append("## 2. What the record constrains, and what drives the outcome\n\n"
               f"Rejection calibration against all anchors (n = {6 * N:,}; "
               "`calibrate_*.csv`):\n\n" + "\n".join(cal_lines)
               + f"\n\nFirst-order variance share of P(airbridge) by parameter (n = {4 * N:,}; "
               "`screen_*.csv`), parameters above twice the noise floor:\n\n"
               + "\n".join(scr_lines)
               + f"\n\nParameters flagged as assumptions: {n_ass}.")

    # 3. factor swaps -------------------------------------------------------------
    _say(cfg, "factor swaps")
    swap_parts = []
    pairs = [(a, b) for a, b in itertools.permutations(scen, 2) if a.family == b.family]
    if cfg.pairs is not None:
        wanted = {frozenset(p) for p in cfg.pairs}
        pairs = [(a, b) for a, b in pairs if frozenset((a.id, b.id)) in wanted]
    n_crt = max(50, int(N * 0.4))
    donor_scans: dict[tuple, list[dict]] = {}
    for h, w in pairs:
        res_by_r = {}
        for r, n in (("lanchester", N), ("crt", n_crt)):
            _say(cfg, f"  swap {h.id} <- {w.id} ({r})")
            res = experiment.factor_swap(_variant(h, r), _variant(w, r), n, seed,
                                         factors=cfg.factors, workers=W)
            t = analysis.shapley_table(res)
            res_by_r[r] = (res, t)
            k = len(res.factors)
            pair = f"{h.id}__{w.id}.{r}"
            values[f"swap.{pair}.base"] = res.value((0,) * k)
            values[f"swap.{pair}.full"] = res.value((1,) * k)
            for row in t.itertuples():
                values[f"shapley.{pair}.{row.factor}"] = float(row.shapley)
                values[f"single.{pair}.{row.factor}"] = float(row.single_swap_p)
            meta = {"home": h.fingerprint(), "away": w.fingerprint(), "n": n, "seed": seed,
                    "resolver": r}
            experiment.save(res.table(), out, f"swap_{h.id}__{w.id}_{r}", meta)
            experiment.save(t, out, f"shapley_{h.id}__{w.id}_{r}", meta)
        factors = res_by_r["lanchester"][0].factors
        key = (w.id, tuple(factors))
        if key not in donor_scans:
            _say(cfg, f"  donor check {w.id}")
            donor_scans[key] = donor_scan(_variant(w, "lanchester"), factors, N, seed, W)
        swap_parts.append(
            _swap_section(h, w, _ends(res_by_r), {r: t for r, (_, t) in res_by_r.items()})
            + donor_section(h, w, donor_scans[key], res_by_r["lanchester"][1], N, seed, W,
                            values, out))
        from . import plots
        plots.shapley_bars({r: t for r, (_, t) in res_by_r.items()},
                           {r: f"{h.id} + {w.id} factors ({r})" for r in res_by_r},
                           str(out / f"shapley_{h.id}__{w.id}.png"))
    sec.append("## 3. Cross-battle factor swaps\n\n"
               "Full factorial over the factor bundles (same seeds throughout), decomposed "
               "with exact Shapley values; intervals are 90% bootstrap over runs (Monte Carlo "
               f"noise only). Lanchester n = {N:,} per configuration, CRT n = {n_crt:,}. "
               "`Single` is P(airbridge) with only that factor swapped (Lanchester).\n\n"
               + "\n\n".join(swap_parts))

    # 3b. context swaps -----------------------------------------------------------
    if cfg.context_pairs:
        _say(cfg, "context swaps")
        sec.append(_context_section(cfg, by_id, values, out, n_crt))

    # 4. go/no-go rule variants --------------------------------------------------
    if cfg.go_rule_pair and all(x in by_id for x in cfg.go_rule_pair):
        _say(cfg, "go/no-go rule variants")
        sec.append(_go_rule_section(cfg, by_id[cfg.go_rule_pair[0]],
                                    by_id[cfg.go_rule_pair[1]], out))

    # 5b. one-parameter sweeps ---------------------------------------------------
    rows_ls = []
    for tag, sid, param, xs, fixed in cfg.line_sweeps:
        if sid not in by_id:
            continue
        _say(cfg, f"line sweep {tag}")
        sc = by_id[sid].with_overrides(fixed) if fixed else by_id[sid]
        df = experiment.sweep(sc, {param: list(xs)}, N, seed, workers=W)
        experiment.save(df, out, f"linesweep_{tag}", {"scenario": sc.fingerprint(), "n": N,
                                                      "seed": seed, "fixed": fixed})
        for x, pv in zip(df[param], df["p"]):
            values[f"linesweep.{tag}.{x:g}"] = float(pv)
            rows_ls.append({"sweep": tag, "x": x, "p": pv})
    if rows_ls:
        t = pd.DataFrame(rows_ls).pivot_table(index="sweep", columns="x", values="p")
        t.columns = [f"{c:g}" for c in t.columns]
        sec.append("## 5b. One-parameter sweeps\n\n"
                   f"P(airbridge), n = {N:,} per point (`linesweep_*.csv`). "
                   + "; ".join(f"`{tag}`: {sid}, `{param}`" + (f" with {fixed}" if fixed else "")
                               for tag, sid, param, _, fixed in cfg.line_sweeps)
                   + ".\n\n" + md_table(t.reset_index()))

    # 5. sweep ------------------------------------------------------------------
    if cfg.sweep_scenario and cfg.sweep_scenario in by_id:
        _say(cfg, "sweep")
        s = by_id[cfg.sweep_scenario]
        ns = max(50, int(N * 0.3))
        df = experiment.sweep(s, cfg.sweep_grid, ns, seed, workers=W)
        experiment.save(df, out, f"sweep_{s.id}",
                        {"scenario": s.fingerprint(), "grid": cfg.sweep_grid, "n": ns,
                         "seed": seed})
        x, y = list(cfg.sweep_grid)
        from . import plots
        plots.sweep_heatmap(df, x, y, str(out / f"sweep_{s.id}.png"),
                            f"{s.id}: P(airbridge)")
        box = df[df[x].isin(_in_box(df[x], s.space[x].dist.bounds()))
                 & df[y].isin(_in_box(df[y], s.space[y].dist.bounds()))]
        rng_txt = (f"{box.p.min():.2f} to {box.p.max():.2f}" if len(box) else "n/a")
        sec.append(f"## 5. Counterfactual surface for {s.id}\n\n"
                   f"P(airbridge) over `{x}` and `{y}` (n = {ns} per cell; "
                   f"`sweep_{s.id}.png`). Grid cells inside the scenario's own prior box "
                   f"(or nearest to it) give {rng_txt}.\n\n"
                   + md_table(_pivot(df, x, y)))

    # 6. resolvers --------------------------------------------------------------
    rt = pd.DataFrame(expected_loss_rates([0.5, 1, 1.5, 2, 3, 4, 5]))
    experiment.save(rt, out, "resolvers", {"kill_rate": 0.01, "round_h": 1.0})
    sec.append("## 6. The two combat resolvers\n\n"
               "Expected loss fraction per hour in the reference engagement (quality 1, no "
               "modifiers). The CRT is illustrative, not calibrated: it is several times "
               "bloodier and its exchange ratio grows roughly linearly with odds instead of "
               "with their square. Read CRT results as a test of structural dependence only."
               "\n\n" + md_table(rt, 3))

    head = (f"# Results summary - battlelab {__version__}\n\n"
            "Generated by `battlelab report` "
            f"({time.strftime('%Y-%m-%d')}, seed {seed}, base n = {N:,}, "
            f"{time.time() - t0:.0f} s on {W} worker(s)). Every number comes from a file in "
            "this folder with a `.manifest.json`; rerun `scripts/reproduce.sh` to regenerate. "
            "Outcome: an airbridge, meaning at least 500 troops air-landed within 48 hours.\n\n"
            "These are statements about the model. Most parameters are flagged assumptions, "
            "and every interval covers Monte Carlo noise only.\n\n"
            "Scenario fingerprints: "
            + ", ".join(f"`{s.id}` {s.fingerprint()}" for s in scen) + ".")
    notes = out / "NOTES.md"
    if notes.exists():
        sec.insert(0, "## Reading these results\n\n" + fill_notes(notes.read_text(), values))
    experiment.save(pd.DataFrame(sorted(values.items()), columns=["key", "value"]), out,
                    "report_values", {"seed": seed, "n": N})
    path = out / "SUMMARY.md"
    path.write_text(head + "\n\n" + "\n\n".join(sec) + "\n")
    _say(cfg, f"wrote {path}")
    return path


NOTE_KEY = re.compile(r"\{\{\s*([^}|\s]+)\s*(?:\|\s*(\w+)\s*)?\}\}")


def fill_notes(text: str, values: dict[str, float]) -> str:
    """Replace {{key}} (or {{key|pct}}, {{key|signed}}) in hand-written notes with
    numbers from this run, so interpretation cannot drift from the tables.
    Unknown keys are an error: the list of valid keys is in report_values.csv."""
    missing = []

    def sub(m: re.Match) -> str:
        key, fmt = m.group(1), m.group(2)
        if key not in values:
            missing.append(key)
            return m.group(0)
        v = values[key]
        if fmt == "pct":
            return f"{100 * v:.0f}%"
        if fmt == "signed":
            return f"{v:+.2f}"
        return f"{v:.2f}"

    out = NOTE_KEY.sub(sub, text)
    if missing:
        keys = ", ".join(sorted(set(missing)))
        raise SystemExit(f"NOTES.md refers to unknown result keys: {keys} "
                         "(valid keys: results/report_values.csv)")
    lines = out.strip().splitlines()
    if lines and lines[0].startswith("# "):   # the notes' own title is replaced by the section's
        lines = lines[1:]
    return "\n".join(lines).strip()


def apply_notes(out_dir: str | Path) -> Path:
    """Re-embed results/NOTES.md into an existing SUMMARY.md using the saved
    report_values.csv, without re-running any experiment."""
    out = Path(out_dir)
    path = out / "SUMMARY.md"
    text = path.read_text()
    vals = pd.read_csv(out / "report_values.csv")
    values = dict(zip(vals["key"], vals["value"].astype(float)))
    start = text.find("## Reading these results")
    if start >= 0:
        end = text.find("\n## ", start + 3)
        text = text[:start] + text[end + 1:]
    first = text.find("\n## ")
    notes = out / "NOTES.md"
    if notes.exists() and first >= 0:
        block = "## Reading these results\n\n" + fill_notes(notes.read_text(), values) + "\n\n"
        text = text[:first + 1] + block + text[first + 1:]
    path.write_text(text)
    return path


def _in_box(values: pd.Series, bounds: tuple[float, float]) -> list[float]:
    """Grid values inside [lo, hi]; the one nearest the midpoint if none are."""
    grid = sorted(set(values))
    lo, hi = bounds
    inside = [v for v in grid if lo - 1e-9 <= v <= hi + 1e-9]
    return inside or [min(grid, key=lambda v: abs(v - 0.5 * (lo + hi)))]


def _pivot(df: pd.DataFrame, x: str, y: str) -> pd.DataFrame:
    piv = df.pivot_table(index=y, columns=x, values="p")
    piv.columns = [f"{x}={c:.2f}" for c in piv.columns]
    return piv.reset_index()


def _ends(res_by_r: dict) -> dict[str, tuple[float, float]]:
    """P(outcome) with nothing and with every bundle swapped, per resolver."""
    out = {}
    for r, (res, _) in res_by_r.items():
        k = len(res.factors)
        out[r] = (res.value((0,) * k), res.value((1,) * k))
    return out


def _swap_section(h: Scenario, w: Scenario, ends: dict[str, tuple[float, float]],
                  tabs: dict[str, pd.DataFrame]) -> str:
    tl, tc = tabs["lanchester"], tabs["crt"]
    (base_l, full_l), (base_c, full_c) = ends["lanchester"], ends["crt"]
    m = tl.set_index("factor").join(tc.set_index("factor"), lsuffix="_l", rsuffix="_c")
    m = m.loc[tl.factor]
    df = pd.DataFrame({
        "factor": m.index,
        "Shapley (Lanchester)": m.shapley_l.values,
        "90% interval": [f"[{a:+.2f}, {b:+.2f}]" for a, b in zip(m.lo90_l, m.hi90_l)],
        "Shapley (CRT)": m.shapley_c.values,
        "Single": m.single_swap_p_l.values,
    })
    top_l = set(tl.factor[:2])
    top_c = set(tc.factor[:2])
    agree = [f for f in tl.factor
             if np.sign(m.loc[f, "shapley_l"]) == np.sign(m.loc[f, "shapley_c"])
             or max(abs(m.loc[f, "shapley_l"]), abs(m.loc[f, "shapley_c"])) < 0.03]
    robust = (f"The two largest contributions are the same under both resolvers "
              f"({' and '.join(sorted(top_l))})" if top_l == top_c else
              f"The two largest contributions differ between resolvers "
              f"(Lanchester: {' and '.join(tl.factor[:2])}; CRT: {' and '.join(tc.factor[:2])})")
    flips = [f for f in tl.factor if f not in agree]
    robust += ("; every factor keeps its sign (or is below 0.03 in both)." if not flips else
               f"; sign differs for {', '.join(flips)}.")
    return (f"**{h.id} given {w.id}'s factors.** P(airbridge) {base_l:.2f} -> {full_l:.2f} "
            f"under Lanchester, {base_c:.2f} -> {full_c:.2f} under CRT. {robust}\n\n"
            + md_table(df))


def _context_section(cfg: ReportConfig, by_id: dict, values: dict, out: Path,
                     n_crt: int) -> str:
    """Section 3b: the listed pairs again, with the shared ctx.* parameters as an
    eighth bundle (CONTEXT). Value keys: ctxswap.*, ctxshapley.*, ctxsingle.*."""
    N, seed, W = cfg.n, cfg.seed, cfg.workers
    parts = []
    for a, b in cfg.context_pairs:
        if a not in by_id or b not in by_id:
            continue
        for h, w in ((by_id[a], by_id[b]), (by_id[b], by_id[a])):
            res_by_r = {}
            for r, n in (("lanchester", N), ("crt", n_crt)):
                _say(cfg, f"  context swap {h.id} <- {w.id} ({r})")
                res = experiment.factor_swap(_variant(h, r), _variant(w, r), n, seed,
                                             factors=cfg.factors, workers=W, context=True)
                t = analysis.shapley_table(res)
                res_by_r[r] = (res, t)
                k = len(res.factors)
                pair = f"{h.id}__{w.id}.{r}"
                values[f"ctxswap.{pair}.base"] = res.value((0,) * k)
                values[f"ctxswap.{pair}.full"] = res.value((1,) * k)
                for row in t.itertuples():
                    values[f"ctxshapley.{pair}.{row.factor}"] = float(row.shapley)
                    values[f"ctxsingle.{pair}.{row.factor}"] = float(row.single_swap_p)
                meta = {"home": h.fingerprint(), "away": w.fingerprint(), "n": n,
                        "seed": seed, "resolver": r, "context": True}
                experiment.save(res.table(), out, f"ctxswap_{h.id}__{w.id}_{r}", meta)
                experiment.save(t, out, f"ctxshapley_{h.id}__{w.id}_{r}", meta)
            shared, only = experiment.context_params(h, w)
            parts.append(_swap_section(h, w, _ends(res_by_r),
                                       {r: t for r, (_, t) in res_by_r.items()}).replace(
                "'s factors.**", "'s factors and shared context.**", 1)
                + f"\n\nCONTEXT = {', '.join(f'`{x}`' for x in shared)}. Not swappable "
                  f"(only one scenario has them, or they are structure): "
                  f"{', '.join(f'`{x}`' for x in only) or 'none'}, plus zones, units "
                  "and the airlift schedule's shape.")
    return ("## 3b. Context swaps\n\n"
            "The same full-factorial swap with one more bundle, CONTEXT: the `ctx.*` "
            "parameters both scenarios have (airfield, airlift and timing values). "
            "Ordinary swaps leave context alone by design (MODELING_STANDARDS §5); this "
            "section asks how much of a difference it explains. Structure (zones, units, "
            "the number of waves) is never swapped.\n\n" + "\n\n".join(parts))


# Donor check (issue #31) ---------------------------------------------------------
DONOR_SAME = 0.99   # share of the donor's runs unchanged that counts as "cannot tell apart"
DONOR_MOVE = 0.03   # single-swap change across that range that earns a full factorial
DONOR_STEPS = 8     # fixed values tried on each side of the prior


def same_runs(a: pd.DataFrame, b: pd.DataFrame) -> np.ndarray:
    """Per run: every metric equal (NaN equals NaN). With common random numbers,
    two batches that differ only in one parameter are compared run for run."""
    cols = [c for c in a.columns if c.startswith("m.")]
    x = a[cols].to_numpy(dtype=float)
    y = b[cols].to_numpy(dtype=float)
    return ((x == y) | (np.isnan(x) & np.isnan(y))).all(axis=1)


def _beyond(lo: float, hi: float) -> tuple[list[float], list[float]]:
    """Fixed values below and above a prior's bounds, nearest first."""
    dn = lo / DONOR_STEPS if lo > 0 else 2 * (hi - lo) / DONOR_STEPS
    up = hi / DONOR_STEPS if hi > 0 else 2 * (hi - lo) / DONOR_STEPS
    below = [round(lo - j * dn, 10) for j in range(1, DONOR_STEPS + 1)]
    above = [round(hi + j * up, 10) for j in range(1, DONOR_STEPS + 1)]
    if lo >= 0:
        below = [x for x in below if x >= 0]
    if lo >= 0 and hi <= 1:          # a share or a probability: stay inside [0, 1]
        above = [x for x in above if x <= 1]
    return below, above


def _joint(df: pd.DataFrame, anchors: list[dict]) -> float:
    if not anchors:
        return float("nan")
    t = analysis.check_anchors(df, anchors)
    return float(t.loc[t.anchor == "ALL (joint)", "share"].iloc[0])


def donor_scan(w: Scenario, factors: list[str], n: int, seed: int = 1,
               workers: int = 1) -> list[dict]:
    """Which parameters of `w`'s swapped bundles does `w` itself not identify?

    Each non-fixed parameter is fixed at both ends of its prior. With common random
    numbers the two batches differ only in that parameter, so when none of the n runs
    changes, `w`'s runs (and with them its anchors, calibration and screening) cannot
    see where in the prior the value lies. For each such parameter, fixed values are
    then tried beyond the prior, nearest first, for as long as at least DONOR_SAME of
    `w`'s runs stay as they are with the shipped prior: that is the range a swap from
    `w` cannot choose between. Returns one dict per flagged parameter."""
    cand = [(f, p) for f in factors for p in w.factors[f] if w.space[p].dist.kind != "fixed"]
    if not cand:
        return []
    ends = experiment.run_batches(
        [w.with_overrides({p: b}) for _, p in cand for b in w.space[p].dist.bounds()],
        n, seed, workers, keep_params=False)
    flagged = [(f, p, ends[2 * i], ends[2 * i + 1]) for i, (f, p) in enumerate(cand)
               if same_runs(ends[2 * i], ends[2 * i + 1]).all()]
    if not flagged:
        return []
    base = experiment.run_batch(w, n, seed, workers, keep_params=False)
    grids = [_beyond(*w.space[p].dist.bounds()) for _, p, _, _ in flagged]
    tries = [(i, x) for i, (below, above) in enumerate(grids) for x in below + above]
    dfs = experiment.run_batches([w.with_overrides({flagged[i][1]: x}) for i, x in tries],
                                 n, seed, workers, keep_params=False)
    got = {(i, x): df for (i, x), df in zip(tries, dfs)}
    out = []
    for i, (f, p, d_lo, d_hi) in enumerate(flagged):
        lo, hi = w.space[p].dist.bounds()
        below, above = grids[i]
        low, high = (lo, d_lo), (hi, d_hi)
        for x in below:
            if same_runs(base, got[(i, x)]).mean() < DONOR_SAME:
                break
            low = (x, got[(i, x)])
        for x in above:
            if same_runs(base, got[(i, x)]).mean() < DONOR_SAME:
                break
            high = (x, got[(i, x)])
        pts = {x: df for x, df in (low, (lo, d_lo), (hi, d_hi), high)}
        points = [{"value": None, "same": 1.0, "joint": _joint(base, w.anchors)}]
        points += [{"value": x, "same": float(same_runs(base, df).mean()),
                    "joint": _joint(df, w.anchors)} for x, df in sorted(pts.items())]
        out.append({"factor": f, "param": p, "lo": lo, "hi": hi, "low": low[0],
                    "high": high[0], "points": points})
    return out


def _num(x: float) -> str:
    return f"{x:.4g}"


def donor_section(h: Scenario, w: Scenario, scan: list[dict], tl: pd.DataFrame,
                  n: int, seed: int, workers: int, values: dict[str, float],
                  out: Path) -> str:
    """The donor check for one swap (Lanchester): the parameters `w`'s own runs cannot
    identify (see `donor_scan`), and the Shapley value and single swap of their
    bundle at the ends of the range `w` cannot tell apart."""
    head = "\n\n*Donor check.* "
    if not scan:
        return (head + f"Every non-fixed parameter in {w.id}'s swapped bundles changes some "
                f"of its runs between the two ends of its prior (n = {n:,}).")
    meta = {"home": h.fingerprint(), "away": w.fingerprint(), "n": n, "seed": seed,
            "resolver": "lanchester", "same": DONOR_SAME, "move": DONOR_MOVE}
    h, w = _variant(h, "lanchester"), _variant(w, "lanchester")
    factors = list(tl.factor)
    shipped = tl.set_index("factor")
    pair = f"{h.id}__{w.id}.lanchester"
    names = ", ".join(f"`{d['param']}` ({d['factor']}, {_num(d['lo'])}-{_num(d['hi'])})"
                      for d in scan)
    text = (head + f"Fixed at either end of its prior (same seeds, n = {n:,}), each of these "
            f"parameters of {w.id}'s swapped bundles changes none of {w.id}'s runs: {names}. "
            f"{w.id}'s anchors, calibration and screening therefore cannot see where in the "
            "prior the value lies, and the Shapley values above rest on that prior wherever "
            "the parameter matters here. Below, each one is fixed across the range over which "
            f"at least {DONOR_SAME:.0%} of {w.id}'s runs stay as they are with the shipped "
            f"prior (Lanchester, n = {n:,}; `donorcheck_{h.id}__{w.id}.csv`).")
    rows_csv = []
    for d in scan:
        f, p = d["factor"], d["param"]
        values[f"donor.{pair}.{p}.low"] = d["low"]
        values[f"donor.{pair}.{p}.high"] = d["high"]
        pts = d["points"]
        ws = [w if pt["value"] is None else w.with_overrides({p: pt["value"]}) for pt in pts]
        singles = [float(shipped.loc[f, "single_swap_p"])] + [
            float(df["m.airbridge"].astype(float).mean()) for df in experiment.run_batches(
                [experiment.variant(h, wx, [f], (1,)) for wx in ws[1:]], n, seed, workers,
                keep_params=False)]
        full = max(abs(s - singles[0]) for s in singles) >= DONOR_MOVE
        phis: list[pd.Series | None] = [shipped.shapley]
        for wx in ws[1:]:
            if full:
                res = experiment.factor_swap(h, wx, n, seed, factors=factors, workers=workers)
                phi = analysis.shapley({m: v.mean() for m, v in res.runs.items()},
                                       len(res.factors))
                phis.append(pd.Series(phi, index=res.factors))
            else:
                phis.append(None)
        rows = []
        for pt, s, ph in zip(pts, singles, phis):
            x = pt["value"]
            label = "shipped prior" if x is None else _num(x)
            if x is not None:
                tag = f"{p}.{_num(x)}"
                values[f"donorsame.{pair}.{tag}"] = pt["same"]
                values[f"donorjoint.{pair}.{tag}"] = pt["joint"]
                values[f"donorsingle.{pair}.{tag}.{f}"] = s
                if ph is not None:
                    for g, v in ph.items():
                        values[f"donorshapley.{pair}.{tag}.{g}"] = float(v)
            top = (" and ".join(ph.abs().sort_values(ascending=False).index[:2])
                   if ph is not None else "")
            row = {f"`{p}`": label, "runs unchanged": f"{pt['same']:.1%}",
                   "joint anchors": pt["joint"], f"{f} Shapley": None if ph is None
                   else float(ph[f]), f"{f} single": s, "two largest": top}
            rows.append(row)
            rows_csv.append({"param": p, "factor": f, "value": x, "donor_same": pt["same"],
                             "donor_joint": pt["joint"], "single": s,
                             "shapley": row[f"{f} Shapley"], "two_largest": top})
        span = (f"`{p}` ({f}): {w.id}'s runs stay the same from {_num(d['low'])} to "
                f"{_num(d['high'])}")
        if full:
            text += f"\n\n{span}.\n\n" + md_table(pd.DataFrame(rows))
        else:
            text += (f"\n\n{span}; {f} swapped alone stays within {DONOR_MOVE:.2f} of the "
                     f"shipped {singles[0]:.2f} over that range ({min(singles):.2f} to "
                     f"{max(singles):.2f}), so its Shapley value was not recomputed.")
    experiment.save(pd.DataFrame(rows_csv), out, f"donorcheck_{h.id}__{w.id}", meta)
    return text


_BLOCK_END = re.compile(r"\n\n(\*\*\S+ given \S+'s factors\.\*\*|## )")


def apply_donor_check(out_dir: str | Path, scenarios: list[str],
                      pairs: list[tuple[str, str]], workers: int = 1) -> Path:
    """Run only the donor check for the listed pairs (both directions) against the
    swaps already saved in `out_dir`, and rewrite those pairs' blocks of section 3
    in SUMMARY.md. Refuses saved swaps made with other scenario versions."""
    import json

    out = Path(out_dir)
    path = out / "SUMMARY.md"
    text = path.read_text()
    vals = pd.read_csv(out / "report_values.csv")
    values = dict(zip(vals["key"], vals["value"].astype(float)))
    by_id = {s.id: s for s in map(Scenario.load, scenarios)}
    scans: dict[tuple, list[dict]] = {}
    for a, b in pairs:
        for h, w in ((by_id[a], by_id[b]), (by_id[b], by_id[a])):
            tabs, ends = {}, {}
            for r in RESOLVER_NAMES:
                name = f"{h.id}__{w.id}_{r}"
                meta = json.loads((out / f"shapley_{name}.manifest.json").read_text())
                if (meta["home"], meta["away"]) != (h.fingerprint(), w.fingerprint()):
                    raise SystemExit(f"{out / name}: saved for other scenario versions; "
                                     "rerun the report")
                tabs[r] = pd.read_csv(out / f"shapley_{name}.csv")
                sw = pd.read_csv(out / f"swap_{name}.csv")
                k = len(tabs[r])
                ends[r] = (float(sw.loc[sw.n_swapped == 0, "p"].iloc[0]),
                           float(sw.loc[sw.n_swapped == k, "p"].iloc[0]))
                if r == "lanchester":
                    n, seed = int(meta["n"]), int(meta["seed"])
                    factors = [c for c in sw.columns if c not in ("n_swapped", "p", "n")]
            key = (w.id, tuple(factors))
            if key not in scans:
                scans[key] = donor_scan(_variant(w, "lanchester"), factors, n, seed, workers)
            block = (_swap_section(h, w, ends, tabs)
                     + donor_section(h, w, scans[key], tabs["lanchester"], n, seed,
                                     workers, values, out))
            header = f"**{h.id} given {w.id}'s factors.**"
            start = text.find(header)
            if start < 0:
                raise SystemExit(f"{path}: no block for {h.id} given {w.id}")
            m = _BLOCK_END.search(text, start + len(header))
            end = m.start() if m else len(text.rstrip("\n"))
            text = text[:start] + block + text[end:]
    path.write_text(text)
    experiment.save(pd.DataFrame(sorted(values.items()), columns=["key", "value"]), out,
                    "report_values", {"seed": seed, "n": n})
    return apply_notes(out)


def _go_rule_section(cfg: ReportConfig, a: Scenario, b: Scenario, out: Path) -> str:
    N, seed, W = cfg.n, cfg.seed, cfg.workers
    n = max(50, N // 2)
    variants: dict[str, dict[str, Any]] = {"threshold": {}, "logistic": {"go_rule": "logistic"},
                "lag 1 h": {"overrides": {"mech.info_lag_h": 1.0}}}
    parts = []
    for h, w in ((a, b), (b, a)):
        cols = {}
        ends = {}
        for name, kw in variants.items():
            res = experiment.factor_swap(_variant(h, **kw), _variant(w, **kw), n, seed,
                                         factors=cfg.factors, workers=W)
            t = analysis.shapley_table(res, boot=200)
            tag = name.replace(" ", "")
            experiment.save(t, out, f"shapley_{h.id}__{w.id}_go_{tag}",
                            {"home": h.fingerprint(), "away": w.fingerprint(), "n": n,
                             "seed": seed, "variant": kw})
            cols[name] = t.set_index("factor").shapley
            k = len(res.factors)
            ends[name] = (res.value((0,) * k), res.value((1,) * k))
            cols[f"single ({name})"] = t.set_index("factor").single_swap_p
        df = pd.DataFrame(cols).reset_index().rename(columns={"index": "factor"})
        df = df.reindex(df["threshold"].abs().sort_values(ascending=False).index)
        span = "; ".join(f"{k} {v[0]:.2f} -> {v[1]:.2f}" for k, v in ends.items())
        parts.append(f"**{h.id} given {w.id}'s factors** ({span}):\n\n"
                     + md_table(df[["factor", "threshold", "logistic", "lag 1 h",
                                    "single (threshold)", "single (logistic)"]]))
    return ("## 4. Does the go/no-go rule drive the swap results?\n\n"
            "The same swaps (Lanchester, n = "
            f"{n:,} per configuration) under the hard threshold, the logistic acceptance rule "
            "(`mech.go_width` 0.02) and a 1-hour information lag on the risk estimate. "
            "Shapley values per factor, and P(airbridge) with that factor swapped alone.\n\n"
            + "\n\n".join(parts))
