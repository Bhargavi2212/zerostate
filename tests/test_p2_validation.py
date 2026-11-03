"""C12: P2's model agrees with the analytic blowdown within 2 % at the x30 step (eval/p2_validation.py)."""

import importlib.util
from pathlib import Path


def test_c12_blowdown_matches_analytic_within_2_pct():
    vspec = importlib.util.spec_from_file_location("p2_validation", Path(__file__).parents[1] / "eval" / "p2_validation.py")
    val = importlib.util.module_from_spec(vspec)
    vspec.loader.exec_module(val)
    r = val.run()
    assert r["step_process_s"] == 1.5 and 270 <= r["vent_process_s"] <= 330  # ~5 process-min
    assert r["max_error_pct"] < 2.0
