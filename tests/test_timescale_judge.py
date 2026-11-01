import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "timescale_test", Path(__file__).parents[1] / "eval" / "tools" / "timescale_test.py")
ts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ts)


def run(mean_p, sd, first, last):
    s = {"mean": mean_p, "mean_err_pct": 100 * abs(mean_p - 2700) / 2700, "sd": sd, "sd_first5": first, "sd_last5": last}
    return {"n": 1, "stats": {"pressure": s, "liquid_level": {**s, "mean_err_pct": 0}}}


def test_judge_criteria():
    v = ts.judge({"1.0": run(2700, 5, 5, 5), "10.0": run(2710, 12, 10, 12), "5.0": run(2700, 20, 5, 20)})
    assert v["1.0"]["pass"] and v["10.0"]["pass"]
    assert not v["5.0"]["pass"]  # sd grew 4x and is 4x the x1 sd
    assert not ts.judge({"1.0": run(2900, 5, 5, 5)})["1.0"]["pass"]  # mean 7 % off nominal


vspec = importlib.util.spec_from_file_location(
    "vent_fidelity", Path(__file__).parents[1] / "eval" / "tools" / "vent_fidelity.py")
vf = importlib.util.module_from_spec(vspec)
vspec.loader.exec_module(vf)


def test_vent_fidelity_judge():
    phys = vf.physics_vent_s(2700)
    assert 340 < phys < 370  # ~5.9 process-min from 2700 to 102 kPa
    good = {"p0": 2700, "vent_s": phys, "physics_vent_s": phys, "curve": {"60": 1900, "120": 1300}}
    slow = {**good, "vent_s": phys * 1.2, "curve": {"60": 2200, "120": 1300}}
    v = vf.judge({"1.0": good, "10.0": good, "5.0": slow})
    assert v["1.0"]["pass"] and v["10.0"]["pass"] and not v["5.0"]["pass"]
