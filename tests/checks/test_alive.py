from checks import synth_p2 as p2
from checks.synth import PARAMS, PLAN, STEP, VENT, steady, vent, window
from zerostate.checks.live import alive
from zerostate.models.verdict import FindingStatus as S


def run(w):
    return alive.check(PLAN, STEP[VENT], w, PARAMS)


def test_pass_gauge_tracks_the_vent():
    assert run(window(vent, 120)).status == S.PASS


def test_fail_gauge_frozen_at_vent_start():
    # S1: pressure frozen while the vent is open and flowing
    assert run(window(lambda ps: vent(ps, pressure=2700.0), 120)).status == S.FAIL


def test_unknown_if_vent_never_opened():
    assert run(window(lambda ps: steady(pressure=2700.0), 120)).status == S.UNKNOWN


# ---------------------------------------------------------------- P2 (v2): gauges by segment, blocked vent, bleed, after-hold


def run_p2(k, w):
    return alive.check(p2.PLAN, p2.STEP[k], w, p2.PARAMS)


def test_p2_pass_both_vessel_gauges_track_the_vent():
    r = run_p2(p2.VENT, p2.opened(p2.isolated(p2.line()), "VV-213", 120))
    assert r.status == S.PASS and "PT-211" in r.message and "PT-212" in r.message


def test_p2_fail_blocked_vent_open_no_flow_no_fall():
    # S10: VV-213 blocked (flow scale 0): feedback open, FT-213 at zero, no fall
    r = run_p2(p2.VENT, p2.opened(p2.isolated(p2.line(**{"VV-213.flow_scale": 0})), "VV-213", 120))
    assert r.status == S.FAIL and "vent blocked" in r.message


def test_p2_pass_bleed_on_feedback_alone():
    m = p2.do(p2.line(), ("XV-201", 0), ("XV-203", 0))
    r = run_p2(p2.BLEED, p2.opened(m, "BV-202", 120))
    assert r.status == S.PASS and r.message.startswith("PT-202 fell")


def test_p2_fail_bleed_gauge_does_not_fall():
    m = p2.do(p2.line(), ("XV-201", 0), ("XV-203", 0))
    m.set("PT-202.fault_mode", 1)
    assert run_p2(p2.BLEED, p2.opened(m, "BV-202", 120)).status == S.FAIL


def _confirmed_p2_bleed(m):
    """The owner-confirmed P2 plan as merged (no segments): v2 judged its bleed on F-210's gauges."""
    import yaml

    from zerostate.models.envelope import IsolationPlan
    plan = IsolationPlan.model_validate(yaml.safe_load((p2.P2 / "plan.yaml").read_text(encoding="utf-8")))
    step = next(s for s in plan.steps if s.target == "BV-202")
    return alive.check(plan, step, p2.opened(m, "BV-202", 120), p2.PARAMS)


def test_p2_confirmed_plan_bleed_is_judged_on_the_cavity_gauge():
    r = _confirmed_p2_bleed(p2.do(p2.line(), ("XV-201", 0), ("XV-203", 0)))
    assert r.status == S.PASS and r.message.startswith("PT-202 fell")


def test_p2_confirmed_plan_bleed_fails_when_the_cavity_gauge_is_frozen():
    m = p2.do(p2.line(), ("XV-201", 0), ("XV-203", 0))
    m.set("PT-202.fault_mode", 1)
    assert _confirmed_p2_bleed(m).status == S.FAIL


def test_p2_pass_after_hold_gauges_follow_the_final_vent():
    m = p2.at_hold(p2.isolated(p2.line()))
    m.step(600)
    r = run_p2(p2.FINAL_VENT, p2.opened(m, "VV-213", 120))
    assert r.status == S.PASS and "after the hold" in r.message


def test_p2_fail_after_hold_frozen_gauges_cannot_follow():
    # S1b: both vessel gauges frozen during the hold while XV-204 leaks
    m = p2.at_hold(p2.isolated(p2.line(**{"XV-204.leak_pct": 0.5})))
    m.set("PT-211.fault_mode", 1)
    m.set("PT-212.fault_mode", 1)
    m.step(600)
    r = run_p2(p2.FINAL_VENT, p2.opened(m, "VV-213", 120))
    assert r.status == S.FAIL and "after the hold" in r.message
