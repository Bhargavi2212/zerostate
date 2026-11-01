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
    assert hold.check(PLAN, STEP[7], net_6, PARAMS | {"hold_max_rise_kpa": 50}).status == S.FAIL
