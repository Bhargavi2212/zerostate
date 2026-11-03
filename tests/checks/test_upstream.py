from checks.synth_p2 import HOLD, PARAMS, PLAN, STEP, at_hold, isolated, line, window
from zerostate.checks.live import upstream
from zerostate.models.verdict import FindingStatus as S


def run(w):
    return upstream.check(PLAN, STEP[HOLD], w, PARAMS)


def test_pass_header_pressure_behind_the_isolation():
    r = run(window(at_hold(isolated(line())), 600))
    assert r.status == S.PASS and "PT-200" in r.message


def test_unknown_when_supply_depressurised_during_the_hold():
    # S11: S-200 depressurised during the hold: a hold with nothing behind it proves nothing (never a pass)
    m = at_hold(isolated(line()))
    r = run(window(m, 600, during=lambda m, ps: ps >= 300 and m.set("S-200.pressure_kpa", 400)))
    assert r.status == S.UNKNOWN and "no pressure behind the isolation" in r.message
