from checks.synth import PARAMS, PLAN, STEP, VENT, steady, vent, window
from zerostate.checks.live import quality
from zerostate.models.verdict import FindingStatus as S


def run(w, k=VENT):
    return quality.check(PLAN, STEP[k], w, PARAMS)


def test_pass_clean_vent():
    assert run(window(vent, 120)).status == S.PASS


def test_fail_dropout_to_zero_is_out_of_range():
    w = window(lambda ps: vent(ps, pressure=0.0) if 30 <= ps < 40 else vent(ps), 120)
    assert run(w).status == S.FAIL


def test_fail_pressure_jump_faster_than_physics():
    w = window(lambda ps: vent(ps, pressure=1500.0) if ps >= 20 else vent(ps), 60)
    r = run(w)
    assert r.status == S.FAIL and "faster than the process" in r.message


def test_unknown_when_a_witness_is_stale():
    w = window(vent, 60, quality=lambda ps, tag: "STALE" if tag == "pressure" and ps > 30 else "GOOD")
    assert run(w).status == S.UNKNOWN


def test_valve_closing_in_one_tick_is_not_a_spike():
    # GRFICS valves have no travel time: f1 flow 640 -> 0 in one poll on a clean run
    w = window(lambda ps: steady(f1_flow=640.0, f1_valve_pos=100.0, f1_cmd=100.0, pressure=2700.0)
               if ps < 10 else steady(pressure=2700.0), 40)
    assert run(w, k=2).status == S.PASS


def test_one_late_stale_poll_is_not_a_rate_failure():
    # Live S0 seed 2: polls stalled, the late one carried a value ~10 process-s old, the next was fresh
    def lagged(ps):
        return vent(30) if 30 <= ps < 41 else vent(ps)
    assert run(window(lagged, 120)).status == S.PASS


def test_rate_still_catches_a_dropout_before_the_floor():
    # gauge falls to 100 kPa (above the 50 floor) instantly from 2700: impossible for the process
    w = window(lambda ps: vent(ps, pressure=100.0) if ps >= 30 else vent(ps), 80)
    r = run(w)
    assert r.status == S.FAIL and "faster than the process" in r.message


def test_v2_still_fails_a_dropout_jump_early_in_the_vent():
    # 2700 -> 0 -> 2700 kPa during the vent: one poll, and three polls (~7.5 process-s) at 0
    for width in (2.5, 7.5):
        w = window(lambda ps, width=width: vent(ps, pressure=0.0) if 20 <= ps < 20 + width else vent(ps), 80)
        assert run(w).status == S.FAIL
        # with the 50 kPa floor switched off, the rate test alone must still catch the jump
        no_floor = quality.check(PLAN, STEP[VENT], w, PARAMS | {"pressure_min_kpa": 0}, )
        assert no_floor.status == S.FAIL and "faster than the process" in no_floor.message, (width, no_floor.message)
