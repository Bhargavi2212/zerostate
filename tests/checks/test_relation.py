from checks import synth_p2 as p2
from checks.synth import PARAMS, PLAN, STEP, VENT, vent, vented_pressure, window
from zerostate.checks.live import relation
from zerostate.models.verdict import FindingStatus as S


def run(w):
    return relation.check(PLAN, STEP[VENT], w, PARAMS)


def test_pass_pressure_agrees_with_valve_law():
    assert run(window(vent, 120)).status == S.PASS


def test_fail_frozen_gauge_disagrees_with_flow():
    r = run(window(lambda ps: vent(ps, pressure=2700.0), 120))
    assert r.status == S.FAIL and "feedback wrong" in r.message


def test_fail_slow_low_drift():
    # S3: gauge drifts low by 4000 kPa per process-hour while the true pressure vents
    r = run(window(lambda ps: vent(ps, pressure=vented_pressure(ps) - 4000 / 3600 * ps), 120))
    assert r.status == S.FAIL


# ---------------------------------------------------------------- P2 (v2): redundant pair + gas vent law, 2-of-3


def run_p2(w, plan=p2.PLAN):
    return relation.check(plan, p2.STEP[p2.VENT], w, p2.PARAMS)


def vent_p2(**faults):
    m = p2.isolated(p2.line())
    for k, v in faults.items():
        m.set(k, v)
    return p2.opened(m, "VV-213", 120)


def test_p2_pass_pair_and_vent_law_agree():
    r = run_p2(vent_p2())
    assert r.status == S.PASS and "agree with the vent law" in r.message


def test_p2_fail_frozen_gauge_is_outvoted_2_of_3():
    # S1: PT-211 frozen at the start of the vent; PT-212 and the vent law agree
    r = run_p2(vent_p2(**{"PT-211.fault_mode": 1}))
    assert r.status == S.FAIL and r.message.startswith("PT-211 disagrees with PT-212 and the vent law")


def test_p2_fail_gauge_drifting_low():
    # S3: PT-211 drifts low (kPa per process-hour)
    r = run_p2(vent_p2(**{"PT-211.fault_mode": 2, "PT-211.fault_severity": -6000}))
    assert r.status == S.FAIL and "PT-211" in r.message


def test_p2_fail_pair_alone_disagrees():
    pair_only = p2.PLAN.model_copy(update={"relations": tuple(r for r in p2.PLAN.relations if r.type == "redundant_pair")})
    r = run_p2(vent_p2(**{"PT-212.fault_mode": 1}), pair_only)
    assert r.status == S.FAIL and "PT-211 and PT-212 disagree" in r.message
