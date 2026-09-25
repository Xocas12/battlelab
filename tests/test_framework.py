"""Tests. Run with `pytest -q` from the repository root."""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from battlelab import analysis, experiment
from battlelab.cmo import export_design, ingest
from battlelab.mechanics import LanchesterPoisson
from battlelab.params import Fixed, LogNormal, Triangular, Uniform, parse_dist
from battlelab.scenario import Scenario

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "scenarios" / "hostomel_2022.yaml"
MAL = ROOT / "scenarios" / "maleme_1941.yaml"
YPB = ROOT / "scenarios" / "ypenburg_1940.yaml"
LUA = shutil.which("lua5.3") or shutil.which("lua")


@pytest.fixture(scope="module")
def host():
    return Scenario.load(HOST)


@pytest.fixture(scope="module")
def mal():
    return Scenario.load(MAL)


# ---------------------------------------------------------------- params ---
@pytest.mark.parametrize("d", [Uniform(1, 3), Triangular(0, 1, 4), LogNormal(2, 1.5), Fixed(7)])
def test_ppf_monotone_and_bounded(d):
    us = np.linspace(0.001, 0.999, 200)
    xs = [d.ppf(u) for u in us]
    assert all(b >= a for a, b in zip(xs, xs[1:]))
    lo, hi = d.bounds()
    if not isinstance(d, LogNormal):
        assert lo - 1e-9 <= min(xs) and max(xs) <= hi + 1e-9


def test_ppf_matches_mean():
    for d in [Uniform(1, 3), Triangular(0, 1, 4), LogNormal(2, 1.5)]:
        us = (np.arange(20000) + 0.5) / 20000
        assert abs(np.mean([d.ppf(u) for u in us]) - d.mean()) < 0.01 * d.mean()


def test_parse_dist_shorthands():
    assert isinstance(parse_dist(3), Fixed)
    assert isinstance(parse_dist([1, 2]), Uniform)
    assert isinstance(parse_dist({"dist": "triangular", "lo": 0, "mode": 1, "hi": 2}), Triangular)


def test_crn_changing_one_param_leaves_others(host):
    a = host.space.sample(7, 3)
    b = host.with_overrides({"risk.tolerance": {"dist": "uniform", "lo": 0.5, "hi": 0.9}}
                            ).space.sample(7, 3)
    assert a["risk.tolerance"] != b["risk.tolerance"]
    assert all(a[k] == b[k] for k in a if k != "risk.tolerance")


# ----------------------------------------------------------- determinism ---
def test_same_seed_same_run(host):
    p = host.space.sample(5, 11)
    w1, _ = host.run(p, 5, 11)
    w2, _ = host.run(p, 5, 11)
    assert w1.metrics == w2.metrics
    assert [(e.t, e.kind, e.data) for e in w1.log] == [(e.t, e.kind, e.data) for e in w2.log]


def test_different_runs_differ(host):
    out = {repr(host.run(host.space.sample(5, i), 5, i)[0].metrics) for i in range(20)}
    assert len(out) > 10


# ------------------------------------------------------------- resolvers ---
def test_lanchester_expected_losses(host):
    w, _ = host.build(host.space.sample(1, 0), 1, 0)
    r = LanchesterPoisson(kill_rate=0.01)
    eff = {"RU": 400.0, "UA": 250.0}
    losses = np.array([[r.resolve(w, "airfield", eff, "RU")[s] for s in ("RU", "UA")]
                       for _ in range(4000)])
    assert losses[:, 0].mean() == pytest.approx(0.01 * 250 * w.dt, rel=0.05)
    assert losses[:, 1].mean() == pytest.approx(0.01 * 400 * w.dt, rel=0.05)


def test_crt_resolver_runs_and_differs(tmp_path):
    doc = yaml.safe_load(HOST.read_text())
    doc["mechanics"]["combat"] = {"resolver": "crt", "round_h": 1.0,
                                  "fire_weight_defend": 1.0, "fire_weight_attack": 2.0}
    s = Scenario(doc, HOST.read_text() + "crt")
    assert not [i for i in s.lint() if i.level == "error" and "mech.kill_rate" not in i.where]
    df = experiment.run_batch(s, 150, seed=3)
    assert df["m.attacker_ever_controls"].mean() > 0.2
    assert any(e.kind == "crt" for e in s.run(s.space.sample(3, 0), 3, 0)[0].log)


# ------------------------------------------------------------ invariants ---
@pytest.mark.parametrize("path", [HOST, MAL, YPB])
def test_invariants(path):
    s = Scenario.load(path)
    lift = 0
    al = s.doc["airlift"]
    for i in range(150):
        p = s.space.sample(9, i)
        w, trace = s.run(p, 9, i, trace=True)
        m = w.metrics
        assert all(u.strength >= 0 for u in w.units.values())
        for z in w.zones.values():
            if z.runway:
                assert 0.0 <= z.runway.usable <= 1.0
            assert z.control in (None, "contested", *w.sides)
        waves = (len(al["waves"]) if al.get("mode") == "waves"
                 else math.ceil(48 / p["ctx.interval_h"]) + 1)
        lift = p["ctx.aircraft"] * p["ctx.troops_per_aircraft"] * waves
        assert m["landed"] <= lift + 1e-6
        if m["t_control"] is not None:
            assert 0 <= m["t_control"] <= s.horizon
        if m["airbridge"]:
            assert m["attacker_ever_controls"]
        assert len(trace) == int(s.horizon / s.dt) + 1


# ------------------------------------------------------------------ lint ---
def test_shipped_scenarios_lint_clean(host, mal):
    ypb = Scenario.load(YPB)
    for s in (host, mal, ypb):
        assert [i for i in s.lint() if i.level == "error"] == []
    for a, b in ((host, mal), (host, ypb), (mal, ypb)):
        assert Scenario.lint_pair(a, b) == []
    mech = {n for n in host.space.names() if n.startswith(("mech.", "doctrine."))}
    for s in (mal, ypb):                              # family constants identical
        assert {n for n in s.space.names() if n.startswith(("mech.", "doctrine."))} == mech
        assert all(s.space[n].dist == host.space[n].dist for n in mech)


def test_landing_on_contested_field():
    """land_contested lets a wave land into a fight, at extra risk, attacking."""
    ypb = Scenario.load(YPB)
    landed_into_fight = 0
    for i in range(60):
        w, _ = ypb.run(ypb.space.sample(2, i), 2, i)
        for e in w.log:
            if e.kind == "airlanding" and e.data["control"] == "contested":
                assert e.data["p_loss"] >= ypb.space["mech.contested_risk"].dist.mean()
                landed_into_fight += 1
    assert landed_into_fight > 10
    off = ypb.with_overrides({"risk.land_contested": 0})
    df = experiment.run_batch(off, 60, seed=2)
    assert (df["m.t_first_landing"].isna() | (df["m.t_control"].notna())).all()


def test_lint_catches_missing_source_and_bad_ref():
    doc = yaml.safe_load(HOST.read_text())
    doc["parameters"]["hold.quality"] = {"dist": "uniform", "lo": 0.5, "hi": 0.7}   # no source
    doc["units"]["ngu_garrison"]["strength"] = "$hold.nonexistent"
    doc["anchors"].append({"id": "x", "metric": "not_a_metric", "op": "eq", "value": 1})
    msgs = " | ".join(str(i) for i in Scenario(doc).lint())
    assert "needs `source:` or `assumption: true`" in msgs
    assert "$hold.nonexistent is not a parameter" in msgs
    assert "unknown metric" in msgs


# --------------------------------------------------------------- shapley ---
def test_shapley_efficiency_and_additivity():
    k = 3
    contrib = np.array([0.3, -0.1, 0.05])
    vals = {m: 0.2 + float(np.dot(m, contrib))
            for m in [(a, b, c) for a in (0, 1) for b in (0, 1) for c in (0, 1)]}
    phi = analysis.shapley(vals, k)
    assert np.allclose(phi, contrib)
    vals[(1, 1, 1)] += 0.12                      # add an interaction
    phi = analysis.shapley(vals, k)
    assert phi.sum() == pytest.approx(vals[(1, 1, 1)] - vals[(0, 0, 0)])
    assert np.allclose(phi - contrib, 0.04)      # interaction split evenly


def test_swap_variants(host, mal):
    all_on = experiment.variant(host, mal, list(host.factors), (1,) * len(host.factors))
    for names in host.factors.values():
        for n in names:
            assert all_on.space[n] == mal.space[n]
    assert all_on.space["ctx.t_relief"] == host.space["ctx.t_relief"]     # context untouched
    none = experiment.variant(host, mal, list(host.factors), (0,) * len(host.factors))
    assert none is host


def test_swap_small_run(host, mal):
    res = experiment.factor_swap(host, mal, 60, seed=2, factors=["RISK", "HOLD"])
    t = analysis.shapley_table(res, boot=50)
    total = res.value((1, 1)) - res.value((0, 0))
    assert t.shapley.sum() == pytest.approx(total)


# ------------------------------------------------------------ anchors ------
def test_anchor_checks(host):
    df = experiment.run_batch(host, 200, seed=4)
    t = analysis.check_anchors(df, host.anchors)
    assert set(t.anchor) == {a["id"] for a in host.anchors} | {"ALL (joint)"}
    joint = t.set_index("anchor").loc["ALL (joint)", "share"]
    assert joint <= t.share[:-1].min() + 1e-12


# ------------------------------------------------------------- CMO bridge --
def test_export_and_ingest_roundtrip(host, tmp_path):
    out = export_design(host, 4, 1, tmp_path / "bl_design.lua")
    text = out.read_text()
    assert text.count("{id=") == 4 and "BL_DESIGN" in text
    if LUA:
        chk = tmp_path / "chk.lua"
        chk.write_text(f"dofile('{out}') assert(#BL_DESIGN.runs == 4) "
                       "assert(BL_DESIGN.runs[1].p['risk.tolerance'] > 0) print('ok')")
        r = subprocess.run([LUA, str(chk)], capture_output=True, text=True)
        assert r.stdout.strip() == "ok"
    log = tmp_path / "console.txt"
    log.write_text("noise\nBLCSV|run,seed,m.airbridge,p.risk.tolerance\n"
                   "BLCSV|0,11,true,0.05\nother\nBLCSV|1,12,false,0.07\n")
    df = ingest(log)
    assert list(df["m.airbridge"]) == [True, False]
    assert df["p.risk.tolerance"].iloc[1] == pytest.approx(0.07)


@pytest.mark.skipif(LUA is None, reason="needs a Lua 5.3 interpreter")
@pytest.mark.parametrize("mode", ["", "--no-io"])
def test_lua_harness_against_mock(tmp_path, mode):
    args = [LUA, "tests/test_harness.lua", "lua", str(tmp_path), "-"] + ([mode] if mode else [])
    r = subprocess.run(args, cwd=ROOT / "cmo", capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALL LUA HARNESS TESTS PASSED" in r.stdout


@pytest.mark.skipif(LUA is None, reason="needs a Lua 5.3 interpreter")
def test_lua_harness_with_python_design(host, tmp_path):
    design = export_design(host, 3, 5, tmp_path / "bl_design.lua")
    r = subprocess.run([LUA, "tests/test_harness.lua", "lua", str(tmp_path), str(design)],
                       cwd=ROOT / "cmo", capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    df = ingest(tmp_path / "battlelab_results.csv")
    assert len(df) == 3
    assert {f"p.{n}" for n in host.space.names()} <= set(df.columns)
    ref = experiment.run_batch(host, 3, seed=5)
    assert np.allclose(df["p.risk.tolerance"], ref["p.risk.tolerance"], rtol=1e-5)


# ------------------------------------------------------- determinism (2) ---
def test_runs_identical_across_hash_seeds(tmp_path):
    """String hashing is randomised per process; results must not depend on it."""
    code = ("from battlelab.scenario import Scenario\n"
            f"s = Scenario.load(r'{HOST}')\n"
            "print([sorted(s.run(s.space.sample(1, i), 1, i)[0].metrics.items(), key=str)"
            " for i in range(25)])\n")
    outs = set()
    for h in ("1", "2", "3"):
        env = {**__import__("os").environ, "PYTHONHASHSEED": h}
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        outs.add(r.stdout)
    assert len(outs) == 1


# ----------------------------------------------------- command decisions ---
def _events(w, kind):
    return [e for e in w.log if e.kind == kind]


def test_command_decisions_on_schedule_and_orders_at_night(mal):
    seen_order = False
    for i in range(80):
        p = mal.space.sample(3, i)
        w, _ = mal.run(p, 3, i)
        cycle = p["hold.decision_h"]
        for e in _events(w, "command_decision"):
            k = e.t / cycle
            assert e.t >= cycle - 1e-9
            assert k - math.floor(k + 1e-9) < w.dt / cycle + 1e-9   # first turn at/after a point
        for e in _events(w, "leaves_fight"):
            if e.data["reason"] == "ordered_withdrawal":
                seen_order = True
                clock = (mal.h_hour + e.t) % 24
                assert not (6.0 <= clock < 20.0), "night_moves order executed by day"
    assert seen_order


def test_command_cycle_reduces_to_continuous_hazard(mal):
    """decision_h <= dt, no comms loss and no night rule: identical to no command block."""
    plain = mal.with_overrides({"hold.decision_h": 0.0, "hold.comms_loss": 0.0,
                                "hold.night_moves": 0})
    doc = yaml.safe_load(MAL.read_text())
    m = doc["units"]["nz_22_bn"]["morale"]
    for k in ("decision_h", "comms_loss", "fog", "night_moves"):
        m.pop(k)
    bare = Scenario(doc, MAL.read_text() + "bare")
    for i in range(40):
        p = plain.space.sample(5, i)
        assert plain.run(p, 5, i)[0].metrics == bare.run(p, 5, i)[0].metrics


def test_fog_makes_withdrawal_earlier(mal):
    """Blind decisions with pessimistic fog can only raise the order hazard."""
    blind = mal.with_overrides({"hold.comms_loss": 1.0, "hold.fog": 0.9})
    clear = mal.with_overrides({"hold.comms_loss": 0.0})
    a = experiment.run_batch(blind, 300, seed=6)["m.attacker_ever_controls"].mean()
    b = experiment.run_batch(clear, 300, seed=6)["m.attacker_ever_controls"].mean()
    assert a > b + 0.1


# ------------------------------------------------------------ go / no-go ---
def _airlift(scenario, run=0):
    w, mechs = scenario.build(scenario.space.sample(1, run), 1, run)
    al = next(m for m in mechs if m.name == "airlift")
    al.setup(w)
    return w, al


def test_logistic_go_rule_acceptance_curve(host):
    s = host.with_go_rule("logistic")
    tol, width = 0.05, 0.02
    for p in (0.03, 0.05, 0.08):
        acc = []
        for i in range(1500):
            w, al = _airlift(s, i)
            w.sides["RU"].doctrine["risk_tolerance"] = tol
            acc.append(p <= al.tolerance(w, "wave0"))
            assert al.tolerance(w, "wave0") == al.tolerance(w, "wave0")   # one nerve per wave
        assert np.mean(acc) == pytest.approx(1 / (1 + math.exp((p - tol) / width)), abs=0.04)


def test_info_lag_uses_old_risk(host):
    s = host.with_overrides({"mech.info_lag_h": 1.0})
    w, al = _airlift(s)
    al.s.info_lag_h = 1.0
    w.persist["airlift"]["p_hist"] = [(0.0, 0.01), (0.5, 0.02), (1.0, 0.30), (1.5, 0.40)]
    w.t = 1.75
    assert al.p_estimate(w) == 0.02


def test_logistic_rule_removes_denial_cliff(host, mal):
    """Under the hard threshold, Maleme's DENIAL alone makes a Hostomel airbridge
    impossible; the logistic rule turns that cliff into a slope."""
    names = host.factors["DENIAL"]
    hard = host.with_params_from(mal, names)
    soft = host.with_go_rule("logistic").with_params_from(mal, names)
    assert experiment.run_batch(hard, 200, seed=2)["m.airbridge"].mean() == 0.0
    assert experiment.run_batch(soft, 200, seed=2)["m.airbridge"].mean() > 0.0


def test_unknown_go_rule_rejected(host):
    with pytest.raises(ValueError):
        host.with_go_rule("coinflip")


# ---------------------------------------------------------------- schema ---
def test_lint_reports_unknown_and_missing_keys_with_paths():
    doc = yaml.safe_load(HOST.read_text())
    doc["units"]["vdv_assault"]["arrive"]["aircrafts"] = 20            # typo
    del doc["units"]["ua_counterattack"]["arrive"]["zone"]              # missing
    doc["mechanics"]["combat"]["resolver"] = "dice"                     # bad enum
    doc["sides"]["RU"]["doctrine"]["risk_tolerence"] = 0.1              # free-form: warning
    doc["zones"]["airfield"]["runway"]["crater"] = 0.2
    issues = Scenario(doc).lint()
    by_where = {i.where: i for i in issues}
    assert by_where["units.vdv_assault.arrive.aircrafts"].level == "error"
    assert "unknown key" in by_where["units.vdv_assault.arrive.aircrafts"].message
    assert any(i.where == "units.ua_counterattack.arrive" and "'zone'" in i.message
               for i in issues)
    assert by_where["mechanics.combat.resolver"].level == "error"
    assert by_where["sides.RU.doctrine.risk_tolerence"].level == "warning"
    assert by_where["zones.airfield.runway.crater"].level == "error"


def test_schema_tracks_dataclasses():
    """A new field on a spec class is accepted by lint without editing the schema."""
    from battlelab.scenario import SCHEMA
    assert "night_moves" in SCHEMA["morale"][0]
    assert {"t", "zone"} <= SCHEMA["arrive"][1]
    assert "unit" in SCHEMA["airlift"][1] and "unit_id" not in SCHEMA["airlift"][0]


# -------------------------------------------------------------- parallel ---
def test_parallel_batches_match_serial(host, mal):
    a = experiment.run_batch(mal, 40, seed=8)
    b = experiment.run_batch(mal, 40, seed=8, workers=2)
    assert a.equals(b)
    s1 = experiment.factor_swap(host, mal, 20, seed=8, factors=["RISK", "HOLD"])
    s2 = experiment.factor_swap(host, mal, 20, seed=8, factors=["RISK", "HOLD"], workers=2)
    assert all(np.array_equal(s1.runs[k], s2.runs[k]) for k in s1.runs)


# ------------------------------------------------------ backend compare ---
def test_compare_backends_pairs_runs_and_flags_design_mismatch(host):
    a = experiment.run_batch(host, 60, seed=3)
    b = a.copy()
    b.loc[:9, "m.airbridge"] = ~b.loc[:9, "m.airbridge"].astype(bool)
    t, info = analysis.compare_backends(a, b)
    assert info["n_paired"] == 60 and info["param_mismatch"] == []
    row = t.set_index("metric").loc["airbridge"]
    assert row["agree"] == pytest.approx(50 / 60)
    assert row["only_a"] + row["only_b"] == 10
    assert t.set_index("metric").loc["landed", "diff"] == pytest.approx(0.0)
    c = experiment.run_batch(host, 60, seed=4)
    assert "risk.tolerance" in analysis.compare_backends(a, c)[1]["param_mismatch"]


@pytest.mark.skipif(LUA is None, reason="needs a Lua 5.3 interpreter")
def test_compare_backends_cli_on_mock_cmo(host, tmp_path, capsys):
    from battlelab.cli import main
    design = export_design(host, 3, 5, tmp_path / "bl_design.lua")
    r = subprocess.run([LUA, "tests/test_harness.lua", "lua", str(tmp_path), str(design)],
                       cwd=ROOT / "cmo", capture_output=True, text=True)
    assert r.returncode == 0
    native = tmp_path / "native.csv"
    experiment.run_batch(host, 3, seed=5).to_csv(native, index=False)
    main(["compare-backends", str(native), str(tmp_path / "battlelab_results.csv")])
    out = capsys.readouterr().out
    assert "3 paired runs" in out and "WARNING" not in out
    assert any(ln.split()[:2] == ["airbridge", "share"] for ln in out.splitlines())


def test_resolver_loss_rates():
    from battlelab.mechanics.combat import expected_loss_rates
    rows = expected_loss_rates([0.5, 1, 2, 3, 5])
    for r in rows:
        assert r["lan_exchange"] == pytest.approx(r["odds"] ** 2)       # square law
    ex = [r["crt_exchange"] for r in rows]
    assert all(b > a for a, b in zip(ex, ex[1:]))                        # monotone in odds
    assert [r["crt_p_retreat"] for r in rows][-1] == 1.0


# ---------------------------------------------------------------- report ---
def test_report_smoke(tmp_path):
    from battlelab.report import ReportConfig, run_report
    cfg = ReportConfig(scenarios=[str(HOST), str(MAL)], n=12, seed=2, out=str(tmp_path),
                       sweep_scenario="hostomel_2022",
                       sweep_grid={"risk.tolerance": [0.05, 0.3], "denial.t_fires": [2.0, 6.0]},
                       go_rule_pair=("hostomel_2022", "maleme_1941"),
                       factors=["RISK", "HOLD"], log=False)
    text = run_report(cfg).read_text()
    for head in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6."):
        assert head in text
    assert "hostomel_2022 given maleme_1941's factors" in text
    assert (tmp_path / "anchors_maleme_1941_crt.manifest.json").exists()
    assert (tmp_path / "shapley_hostomel_2022__maleme_1941_lanchester.csv").exists()


@pytest.mark.skipif(LUA is None, reason="needs a Lua 5.3 interpreter")
@pytest.mark.parametrize("mode", [[], ["--write"]])
def test_cmo_probe_against_mock(tmp_path, mode):
    r = subprocess.run([LUA, "tests/test_probe.lua", "lua", str(tmp_path)] + mode,
                       cwd=ROOT / "cmo", capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PROBE OK" in r.stdout


def test_export_design_offset(host, tmp_path):
    out = export_design(host, 2, 1, tmp_path / "d.lua", start=5).read_text()
    assert "{id=5," in out and "{id=6," in out and "{id=0," not in out
    ref = host.space.sample(1, 5)["risk.tolerance"]
    assert repr(float(ref)) in out


@pytest.mark.skipif(LUA is None, reason="needs a Lua 5.3 interpreter")
def test_cmo_build_script_end_to_end(tmp_path):
    """Empty world -> bl_build_hostomel.lua -> selftest -> 3 replications via bl_run.lua."""
    r = subprocess.run([LUA, "tests/test_build.lua", "lua", str(tmp_path),
                        str(ROOT / "cmo" / "pilot" / "bl_design.lua")],
                       cwd=ROOT / "cmo", capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "BUILD END-TO-END PASSED" in r.stdout
    df = ingest(tmp_path / "battlelab_results.csv")
    assert len(df) == 3 and (df["m.vdv_delivered"] > 0).any()
