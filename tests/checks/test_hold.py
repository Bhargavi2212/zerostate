from checks import synth_p2 as p2
from checks.synth import HOLD, PARAMS, PLAN, STEP, steady, window
from zerostate.checks.live import hold
from zerostate.models.verdict import FindingStatus as S


def run(w):
    return hold.check(PLAN, STEP[HOLD], w, PARAMS)


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


def test_clean_hold_falls_and_passes_at_1_kpa():
    # live S0 holds fell 3.5-5.4 kPa (reaction keeps consuming vapour)
    assert run(window(lambda ps: steady(pressure=99.0 - 5.4 * ps / 600), 600)).status == S.PASS


def test_small_leak_on_a_falling_baseline_fails_at_1_kpa():
    # 0.3 % f1 leak adds ~+9 kPa over the hold; on the worst clean fall (-5.4) that nets ~+3.6
    r = run(window(lambda ps: steady(pressure=99.0 + (9.0 - 5.4) * ps / 600), 600))
    assert r.status == S.FAIL and "limit 1" in r.message


def test_threshold_can_tighten_but_not_loosen_the_plan():
    net_6 = window(lambda ps: steady(pressure=99.0 + 6.0 * ps / 600), 600)
    plan_limit = PLAN.hold_test.max_rise_kpa
    assert plan_limit < 6
    # a loose threshold cannot override the plan's limit
    assert hold.check(PLAN, STEP[HOLD], net_6, PARAMS | {"hold_max_rise_kpa": 50}).status == S.FAIL


# ---------------------------------------------------------------- P2 (v3): residual-pressure hold, final vent


def run_p2(k, w):
    return hold.check(p2.PLAN, p2.STEP[k], w, p2.PARAMS)


def test_p2_pass_flat_hold_at_residual_pressure():
    r = run_p2(p2.HOLD, p2.window(p2.at_hold(p2.isolated(p2.line())), 600))
    assert r.status == S.PASS and "PT-211 held" in r.message and "PT-212 held" in r.message and "PT-202" in r.message


def test_p2_fail_backflow_through_xv204_rises_the_hold():
    # S4-small: XV-204 passing 0.3 %
    r = run_p2(p2.HOLD, p2.window(p2.at_hold(p2.isolated(p2.line(**{"XV-204.leak_pct": 0.3}))), 600))
    assert r.status == S.FAIL and "energy is getting back in" in r.message


def test_p2_fail_cavity_pressure_with_the_bleed_open():
    # XV-201 passing into the cavity faster than BV-202 bleeds it
    r = run_p2(p2.HOLD, p2.window(p2.at_hold(p2.isolated(p2.line(**{"XV-201.leak_pct": 1.0}))), 600))
    assert r.status == S.FAIL and "PT-202" in r.message and "between the blocks" in r.message


def test_p2_pass_final_vent_ends_depressurised():
    m = p2.at_hold(p2.isolated(p2.line()))
    m.step(600)
    r = run_p2(p2.FINAL_VENT, p2.opened(m, "VV-213", 120))
    assert r.status == S.PASS and "vented to" in r.message


def test_p2_fail_final_vent_not_depressurised():
    m = p2.at_hold(p2.isolated(p2.line()))
    m.step(600)
    m.set("VV-213.flow_scale", 0.1)
    r = run_p2(p2.FINAL_VENT, p2.opened(m, "VV-213", 120))
    assert r.status == S.FAIL and "ends the final vent" in r.message
