"""Baselines (eval/baselines/): the gauge rule on committed p1 episodes, and its scoring in eval/score.py."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
BENCH = ROOT / "eval" / "results" / "bench" / "p1"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gauge = _load("gauge_rule", ROOT / "eval" / "baselines" / "gauge_rule.py")
score = _load("score", ROOT / "eval" / "score.py")


def _ep(prefix):
    return next(p for p in BENCH.iterdir() if p.name.startswith(prefix))


def test_gauge_rule_passes_a_clean_vented_episode():
    d = gauge.decide(_ep("S0_seed1184053442_"))
    assert d["answer"] == "pass" and d["values"]["pressure"] < 150


def test_gauge_rule_passes_a_leak_below_the_meter_cutoff():
    d = gauge.decide(_ep("S4-small_seed1318434843_"))  # true f1 leak, measured 0 below the cutoff
    assert d["answer"] == "pass" and d["values"]["f1_flow"] == 0


def test_gauge_rule_blocks_on_pressure_or_flow_at_the_last_mark():
    d = gauge.decide(_ep("S4-large_seed1200348533_"))  # stopped at step 2, still at plant pressure
    assert d["answer"] == "block" and d["values"]["pressure"] >= 150


def test_nearest_sample_and_missing_reading():
    sig = {"t": [10.0, 11.0, 12.0], "pressure": [1.0, 2.0, None]}
    assert gauge.at(sig, "pressure", 10.6) == 2.0
    assert gauge.at(sig, "pressure", 12.0) == 2.0  # a missing sample is skipped
    assert gauge.at(sig, "f1_flow", 10.0) is None


def test_gauge_rule_scored_with_the_same_hazard_code():
    eps = {p.name: score.load_episode(p) for p in (_ep("S0_seed1184053442_"), _ep("S4-small_seed1318434843_"))}
    b = score.baselines(eps, score.P1_FULL_SCALE, ROOT / "no_muse_results.json")
    g = b["gauge_rule"]
    assert g["dangerous_miss"]["primary"]["k"] == 0 and g["dangerous_miss"]["primary"]["n"] == 2
    assert g["dangerous_miss"]["secondary"]["k"] == 1  # the passed leak: true f1 above 0.1 % after the mark
    assert "muse_alone" not in b
