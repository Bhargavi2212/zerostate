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
