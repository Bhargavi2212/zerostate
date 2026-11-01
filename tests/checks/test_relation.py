from checks.synth import PARAMS, PLAN, STEP, vent, vented_pressure, window
from zerostate.checks.live import relation
from zerostate.models.verdict import FindingStatus as S


def run(w):
    return relation.check(PLAN, STEP[5], w, PARAMS)


def test_pass_pressure_agrees_with_valve_law():
    assert run(window(vent, 120)).status == S.PASS


def test_fail_frozen_gauge_disagrees_with_flow():
    r = run(window(lambda ps: vent(ps, pressure=2700.0), 120))
    assert r.status == S.FAIL and "feedback wrong" in r.message


def test_fail_slow_low_drift():
    # S3: gauge drifts low by 4000 kPa per process-hour while the true pressure vents
    r = run(window(lambda ps: vent(ps, pressure=vented_pressure(ps) - 4000 / 3600 * ps), 120))
    assert r.status == S.FAIL
