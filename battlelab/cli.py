"""battlelab command line.

  battlelab lint scenarios/*.yaml
  battlelab run scenarios/hostomel_2022.yaml -n 4000 --out results/
  battlelab trace scenarios/hostomel_2022.yaml --run 3
  battlelab anchors scenarios/maleme_1941.yaml -n 2000
  battlelab screen scenarios/hostomel_2022.yaml -n 4000
  battlelab calibrate scenarios/maleme_1941.yaml -n 8000
  battlelab swap scenarios/hostomel_2022.yaml scenarios/maleme_1941.yaml -n 1500 --out results/
  battlelab sweep scenarios/hostomel_2022.yaml --grid risk.tolerance=0:0.4:9 \\
                  --grid denial.t_fires=2:12:11 -n 500 --out results/
  battlelab cmo-export scenarios/hostomel_2022.yaml -n 200 --out cmo/lua/battlelab/bl_design.lua
  battlelab cmo-ingest results_cmo.csv --scenario scenarios/hostomel_2022.yaml
  battlelab compare-backends results/hostomel_2022_runs.csv battlelab_results.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import analysis, experiment
from .mechanics import GO_RULES, RESOLVERS
from .scenario import Scenario

FMT = "{:.3f}".format
pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)


def _load(path: str, resolver: str | None = None, go_rule: str | None = None,
          overrides: list[str] | None = None) -> Scenario:
    s = Scenario.load(path)
    if resolver:
        s = s.with_resolver(resolver)
    if go_rule:
        s = s.with_go_rule(go_rule)
    if overrides:
        s = s.with_overrides(_overrides(overrides))
    errors = [i for i in s.lint() if i.level == "error"]
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(f"{path}: {len(errors)} lint error(s); fix before running")
    return s


def _overrides(items: list[str] | None) -> dict:
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        out[k] = float(v)
    return out


def cmd_lint(a):
    bad = 0
    scen = []
    for f in a.files:
        try:
            s = Scenario.load(f)
        except Exception as e:      # malformed YAML or parameter spec
            bad += 1
            print(f"{f}: cannot load: {type(e).__name__}: {e}")
            continue
        scen.append(s)
        issues = s.lint()
        n_err = sum(i.level == "error" for i in issues)
        bad += n_err
        n_ass = sum(p.prov.assumption for _, p in s.space.items())
        print(f"{f}: {len(s.space.names())} parameters ({n_ass} flagged as assumptions), "
              f"{n_err} errors, {len(issues) - n_err} warnings")
        for i in issues:
            print("   ", i)
    for i in range(len(scen)):
        for j in range(i + 1, len(scen)):
            if scen[i].family == scen[j].family:
                for issue in Scenario.lint_pair(scen[i], scen[j]):
                    bad += 1
                    print("   ", issue)
    sys.exit(1 if bad else 0)


def cmd_run(a):
    s = _load(a.scenario, a.resolver, a.go_rule, a.set)
    df = experiment.run_batch(s, a.n, a.seed, a.workers)
    print(analysis.summarize(df).to_string(index=False, float_format=FMT))
    if a.out:
        p = experiment.save(df, a.out, f"{s.id}_runs",
                            {"scenario": s.id, "fingerprint": s.fingerprint(), "n": a.n,
                             "seed": a.seed, "variant": s.variant})
        print(f"saved {p}")


def cmd_trace(a):
    s = _load(a.scenario).with_overrides(_overrides(a.set))
    p = s.space.sample(a.seed, a.run)
    w, trace = s.run(p, a.seed, a.run, trace=True)
    print(f"{s.title} - run {a.run}, seed {a.seed}")
    for e in w.log:
        clock = (s.h_hour + e.t) % 24
        print(f"  H+{e.t:5.2f}  ({int(clock):02d}:{int(clock % 1 * 60):02d})  "
              f"{e.kind:<20} {e.data}")
    print("metrics:", {k: (round(v, 2) if isinstance(v, float) else v)
                       for k, v in w.metrics.items()})
    if a.out:
        pd.DataFrame(trace).to_csv(a.out, index=False)
        print(f"trace written to {a.out}")


def _sfx(a) -> str:
    return "".join(f"_{x}" for x in (getattr(a, "resolver", None), getattr(a, "go_rule", None),
                                     getattr(a, "tag", None)) if x)


def _tag(s: Scenario, a) -> str:
    return s.id + _sfx(a)


def cmd_anchors(a):
    s = _load(a.scenario, a.resolver, a.go_rule, a.set)
    df = experiment.run_batch(s, a.n, a.seed, a.workers)
    t = analysis.check_anchors(df, s.anchors)
    print(t.to_string(index=False, float_format=FMT))
    if a.out:
        from . import plots
        tag = _tag(s, a)
        experiment.save(t, a.out, f"anchors_{tag}", {"scenario": s.fingerprint(), "n": a.n,
                                                    "seed": a.seed, "variant": s.variant})
        plots.anchors_bar({tag: t}, str(Path(a.out) / f"anchors_{tag}.png"))


def cmd_calibrate(a):
    s = _load(a.scenario, a.resolver, a.go_rule, a.set)
    df = experiment.run_batch(s, a.n, a.seed, a.workers)
    use = [x for x in s.anchors if not a.anchors or x["id"] in a.anchors.split(",")]
    post, acc = analysis.abc_posterior(df, use)
    print(f"anchors used: {[x['id'] for x in use]}")
    print(f"acceptance: {acc:.3f} ({int(acc * len(df))} of {len(df)} runs reproduce all of them)")
    print(post.to_string(index=False, float_format=FMT))


def cmd_screen(a):
    s = _load(a.scenario, a.resolver, a.go_rule, a.set)
    df = experiment.run_batch(s, a.n, a.seed, a.workers)
    t = analysis.screen(df, a.metric)
    print(t.to_string(index=False, float_format=FMT))
    if a.out:
        experiment.save(t, a.out, f"screen_{_tag(s, a)}_{a.metric}",
                        {"scenario": s.fingerprint(), "n": a.n, "seed": a.seed})


def cmd_swap(a):
    home, away = (_load(x, a.resolver, a.go_rule, a.set) for x in (a.home, a.away))
    pairs = [(home, away), (away, home)] if a.both else [(home, away)]
    tables, titles = {}, {}
    for h, w in pairs:
        res = experiment.factor_swap(h, w, a.n, a.seed, outcome=a.metric,
                                     workers=a.workers, progress=True)
        t = analysis.shapley_table(res)
        base, full = res.value((0,) * len(res.factors)), res.value((1,) * len(res.factors))
        print(f"\n{h.id} with {w.id}'s factors: P({a.metric}) {base:.3f} -> {full:.3f}")
        print(t.to_string(index=False, float_format=FMT))
        tables[h.id] = t
        titles[h.id] = f"{h.id} + {w.id} factors: {base:.2f} -> {full:.2f}"
        if a.out:
            sfx = _sfx(a)
            experiment.save(res.table(), a.out, f"swap_{h.id}__{w.id}{sfx}",
                            {"home": h.fingerprint(), "away": w.fingerprint(), "n": a.n,
                             "seed": a.seed, "metric": a.metric})
            experiment.save(t, a.out, f"shapley_{h.id}__{w.id}{sfx}",
                            {"home": h.fingerprint(), "away": w.fingerprint(), "n": a.n,
                             "seed": a.seed, "variant": h.variant})
    if a.out:
        from . import plots
        path = Path(a.out) / f"shapley{_sfx(a)}.png"
        plots.shapley_bars(tables, titles, str(path))
        print(f"figure: {path}")


def cmd_sweep(a):
    s = _load(a.scenario, a.resolver, a.go_rule, a.set)
    grid = dict(experiment.parse_grid(g) for g in a.grid)
    df = experiment.sweep(s, grid, a.n, a.seed, a.metric, a.workers)
    print(df.to_string(index=False, float_format=FMT))
    if a.out:
        experiment.save(df, a.out, f"sweep_{_tag(s, a)}",
                        {"scenario": s.fingerprint(), "grid": grid, "n": a.n, "seed": a.seed,
                         "variant": s.variant})
        if len(grid) == 2:
            from . import plots
            x, y = list(grid)
            path = Path(a.out) / f"sweep_{_tag(s, a)}.png"
            plots.sweep_heatmap(df, x, y, str(path), f"{s.id}: P({a.metric})")
            print(f"figure: {path}")


def cmd_cmo_export(a):
    from .cmo import export_design
    s = _load(a.scenario)
    if a.swap_from:
        other = _load(a.swap_from)
        names = [n for f in a.factors.split(",") for n in s.factors[f]]
        s = s.with_params_from(other, names)
    out = export_design(s, a.n, a.seed, a.out, start=a.start)
    print(f"wrote runs {a.start}..{a.start + a.n - 1} to {out}")


def cmd_cmo_ingest(a):
    from .cmo import ingest
    df = ingest(a.results)
    print(f"{len(df)} CMO replications")
    print(analysis.summarize(df).to_string(index=False, float_format=FMT))
    if a.scenario:
        s = _load(a.scenario)
        anchors = [x for x in s.anchors if f"m.{x['metric']}" in df.columns]
        if anchors:
            print(analysis.check_anchors(df, anchors).to_string(index=False, float_format=FMT))


def cmd_resolvers(a):
    from .mechanics.combat import expected_loss_rates
    t = pd.DataFrame(expected_loss_rates([0.5, 1, 1.5, 2, 3, 4, 5], a.kill_rate, a.round_h))
    print("Expected loss fraction per hour, reference engagement (quality 1, no modifiers)")
    print(t.to_string(index=False, float_format=FMT))
    if a.out:
        experiment.save(t, a.out, "resolvers", {"kill_rate": a.kill_rate, "round_h": a.round_h})


def cmd_report(a):
    import glob

    from .report import ReportConfig, run_report
    files = a.scenarios or sorted(glob.glob("scenarios/*.yaml"))
    cfg = ReportConfig(scenarios=files, n=a.n, seed=a.seed, workers=a.workers, out=a.out,
                       sweep_scenario=a.sweep, go_rule_pair=tuple(a.go_pair.split(","))
                       if a.go_pair else None)
    run_report(cfg)


def _read_results(path: str) -> pd.DataFrame:
    from .cmo import ingest
    return ingest(path)     # plain CSV or console log; normalises Lua true/false


def cmd_compare_backends(a):
    x, y = _read_results(a.a), _read_results(a.b)
    t, info = analysis.compare_backends(x, y)
    print(f"{info['n_paired']} paired runs ({info['n_a']} in {a.a}, {info['n_b']} in {a.b}); "
          f"{info['shared_params']} shared parameter columns")
    if info["param_mismatch"]:
        print(f"WARNING: parameter draws differ for {info['param_mismatch']}: "
              "not the same design, so run-by-run pairing is meaningless")
    print(t.to_string(index=False, float_format=FMT))
    if a.out:
        experiment.save(t, a.out, a.name, {"a": a.a, "b": a.b, **info})


def main(argv=None):
    ap = argparse.ArgumentParser(prog="battlelab", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, n=2000):
        p.add_argument("-n", type=int, default=n, help="runs per configuration")
        p.add_argument("-s", "--seed", type=int, default=1)
        p.add_argument("-w", "--workers", type=int, default=1)
        p.add_argument("--resolver", choices=sorted(RESOLVERS),
                       help="override the scenario's combat resolver")
        p.add_argument("--go-rule", choices=list(GO_RULES),
                       help="override the scenario's air-landing go/no-go rule")
        p.add_argument("--set", action="append",
                       help="fix a parameter: name=value (repeatable; applied to every scenario)")
        p.add_argument("--tag", help="suffix for output file names")

    p = sub.add_parser("lint")
    p.add_argument("files", nargs="+")
    p.set_defaults(fn=cmd_lint)

    p = sub.add_parser("run")
    p.add_argument("scenario")
    common(p)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("trace")
    p.add_argument("scenario")
    p.add_argument("--run", type=int, default=0)
    p.add_argument("-s", "--seed", type=int, default=1)
    p.add_argument("--set", action="append")
    p.add_argument("--out", help="write the per-turn state trace to CSV")
    p.set_defaults(fn=cmd_trace)

    p = sub.add_parser("anchors")
    p.add_argument("scenario")
    common(p)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_anchors)

    p = sub.add_parser("calibrate", help="ABC rejection against the scenario's anchors")
    p.add_argument("scenario")
    common(p, 8000)
    p.add_argument("--anchors", help="comma-separated anchor ids (default: all)")
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("screen")
    p.add_argument("scenario")
    common(p, 4000)
    p.add_argument("--metric", default="airbridge")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_screen)

    p = sub.add_parser("swap")
    p.add_argument("home")
    p.add_argument("away")
    common(p, 1000)
    p.add_argument("--metric", default="airbridge")
    p.add_argument("--both", action="store_true", help="also run away->home")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_swap)

    p = sub.add_parser("sweep")
    p.add_argument("scenario")
    common(p, 500)
    p.add_argument("--grid", action="append", required=True, help="name=lo:hi:steps")
    p.add_argument("--metric", default="airbridge")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("cmo-export")
    p.add_argument("scenario")
    p.add_argument("-n", type=int, default=100)
    p.add_argument("-s", "--seed", type=int, default=1)
    p.add_argument("--start", type=int, default=0,
                   help="first run index (split a batch over several CMO sessions)")
    p.add_argument("--swap-from", help="borrow factor bundles from this scenario")
    p.add_argument("--factors", default="", help="comma-separated factors to borrow")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_cmo_export)

    p = sub.add_parser("cmo-ingest")
    p.add_argument("results", help="CSV from the harness, or a console log with BLCSV| lines")
    p.add_argument("--scenario")
    p.set_defaults(fn=cmd_cmo_ingest)

    p = sub.add_parser("report", help="run the standard pipeline and write SUMMARY.md")
    p.add_argument("scenarios", nargs="*", help="default: scenarios/*.yaml")
    p.add_argument("-n", type=int, default=1000, help="base runs per configuration")
    p.add_argument("-s", "--seed", type=int, default=1)
    p.add_argument("-w", "--workers", type=int, default=experiment.cpu_workers())
    p.add_argument("--out", default="results")
    p.add_argument("--sweep", default="hostomel_2022", help="scenario id to sweep")
    p.add_argument("--go-pair", default="hostomel_2022,maleme_1941",
                   help="scenario ids for the go/no-go rule comparison")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("resolvers", help="loss rates of the combat resolvers side by side")
    p.add_argument("--kill-rate", type=float, default=0.01)
    p.add_argument("--round-h", type=float, default=1.0)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_resolvers)

    p = sub.add_parser("compare-backends",
                       help="compare two result tables (e.g. native vs CMO) run by run")
    p.add_argument("a", help="native run CSV (battlelab run --out)")
    p.add_argument("b", help="CMO results CSV or console log")
    p.add_argument("--out")
    p.add_argument("--name", default="compare_backends")
    p.set_defaults(fn=cmd_compare_backends)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
