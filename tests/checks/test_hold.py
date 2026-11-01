from checks.synth import PARAMS, PLAN, STEP, steady, window
from zerostate.checks.live import hold
from zerostate.models.verdict import FindingStatus as S


def run(w):
    return hold.check(PLAN, STEP[7], w, PARAMS)


def test_pass_flat_hold():
    assert run(window(lambda ps: steady(), 600)).status == S.PASS


def test_fail_pressure_rises():
    # S4 below the cutoff: a 1 % f1 leak adds ~30 kPa over 600 process-s
    assert run(window(lambda ps: steady(pressure=101 + 30 * ps / 600), 600)).status == S.FAIL


def test_fail_ends_above_depressurised_limit():
    assert run(window(lambda ps: steady(pressure=106.0), 600)).status == S.FAIL


def test_unknown_when_quality_not_pass():
    w = window(lambda ps: steady(), 600, quality=lambda ps, tag: "STALE" if tag == "pressure" and ps > 300 else "GOOD")
    assert run(w).status == S.UNKNOWN


def test_unknown_when_window_incomplete():
    assert run(window(lambda ps: steady(), 300)).status == S.UNKNOWN
