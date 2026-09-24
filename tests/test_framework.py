"""Tests. Run with `pytest -q` from the repository root."""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import yaml

from battlelab import analysis, experiment
from battlelab.cmo import export_design, ingest
from battlelab.mechanics import LanchesterPoisson
from battlelab.params import Fixed, LogNormal, ParamSpace, Triangular, Uniform, parse_dist
from battlelab.scenario import Scenario

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "scenarios" / "hostomel_2022.yaml"
MAL = ROOT / "scenarios" / "maleme_1941.yaml"
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
@pytest.mark.parametrize("path", [HOST, MAL])
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
        waves = len(al["waves"]) if al.get("mode") == "waves" else math.ceil(48 / p["ctx.interval_h"]) + 1
        lift = p["ctx.aircraft"] * p["ctx.troops_per_aircraft"] * waves
        assert m["landed"] <= lift + 1e-6
        if m["t_control"] is not None:
            assert 0 <= m["t_control"] <= s.horizon
        if m["airbridge"]:
            assert m["attacker_ever_controls"]
        assert len(trace) == int(s.horizon / s.dt) + 1


# ------------------------------------------------------------------ lint ---
def test_shipped_scenarios_lint_clean(host, mal):
    assert [i for i in host.lint() if i.level == "error"] == []
    assert [i for i in mal.lint() if i.level == "error"] == []
    assert Scenario.lint_pair(host, mal) == []


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
    for f, names in host.factors.items():
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
        assert subprocess.run([LUA, str(chk)], capture_output=True, text=True).stdout.strip() == "ok"
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
