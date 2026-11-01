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
