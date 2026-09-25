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
    n_crt = max(50, int(N * 0.4))
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
        swap_parts.append(_swap_section(h, w, res_by_r, N, n_crt))
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

    # 4. go/no-go rule variants --------------------------------------------------
    if cfg.go_rule_pair and all(x in by_id for x in cfg.go_rule_pair):
        _say(cfg, "go/no-go rule variants")
        sec.append(_go_rule_section(cfg, by_id[cfg.go_rule_pair[0]],
                                    by_id[cfg.go_rule_pair[1]], out))

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


def _swap_section(h: Scenario, w: Scenario, res_by_r: dict, n_lan: int, n_crt: int) -> str:
    (rl, tl), (rc, tc) = res_by_r["lanchester"], res_by_r["crt"]
    k = len(rl.factors)
    base_l, full_l = rl.value((0,) * k), rl.value((1,) * k)
    base_c, full_c = rc.value((0,) * k), rc.value((1,) * k)
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
