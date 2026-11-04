from checks.synth import ISOLATE_F1, MODE, PARAMS, PLAN, STEP, steady, window
from zerostate.checks.live import valve
from zerostate.models.verdict import FindingStatus as S


def run(w, k=ISOLATE_F1):
    return valve.check(PLAN, STEP[k], w, PARAMS)


def test_pass_f1_isolated():
    assert run(window(lambda ps: steady(pressure=2700.0), 80)).status == S.PASS


def test_fail_commanded_state_wrong():
    # S5 / S6: f1 still commanded open
    r = run(window(lambda ps: steady(pressure=2700.0, f1_cmd=100.0, f1_valve_pos=100.0, f1_flow=640.0), 80))
    assert r.status == S.FAIL and "commanded state wrong" in r.message


def test_fail_flow_through_a_valve_reading_closed():
    # S8: stuck open, feedback reads closed; S4: passing valve above the cutoff
    r = run(window(lambda ps: steady(pressure=2700.0, f1_flow=640.0), 80))
    assert r.status == S.FAIL and "reading closed" in r.message


def test_fail_valve_did_not_reach_position():
    r = run(window(lambda ps: steady(pressure=2700.0, f1_valve_pos=40.0, f1_flow=256.0), 80))
    assert r.status == S.FAIL and "did not reach" in r.message


def test_transient_before_settle_is_ignored():
    w = window(lambda ps: steady(pressure=2700.0, f1_valve_pos=50.0, f1_flow=320.0) if ps < 30 else steady(pressure=2700.0), 80)
    assert run(w).status == S.PASS


def test_mode_step_needs_manual_mode():
    assert run(window(lambda ps: steady(), 20), k=MODE).status == S.PASS
    assert run(window(lambda ps: steady(manual_mode=0.0), 20), k=MODE).status == S.FAIL


def test_unknown_without_samples_after_settle():
    assert run(window(lambda ps: steady(), 40)).status == S.UNKNOWN  # settle is 60 process-s


def test_monitor_pairs_logged_before_settle_ends_still_replay():
    w = window(lambda ps: steady(pressure=2700.0, f1_flow=640.0), 20)
    assert valve.check(PLAN, STEP[2], w, PARAMS, only=[("f1", 0.0)]).status == S.FAIL
    assert valve.check(PLAN, STEP[2], w, PARAMS, only=[("f1", 0.0, 0.0)]).status == S.FAIL


def test_valve_without_a_flow_witness_is_checked_on_command_and_feedback():
    # P2: most block valves have no flow meter of their own (v1 returned UNKNOWN for every such valve)
    plan = PLAN.model_copy(update={"witnesses": [w for w in PLAN.witnesses if w.role != "flow"]})
    assert valve.check(plan, STEP[ISOLATE_F1], window(lambda ps: steady(pressure=2700.0), 80), PARAMS).status == S.PASS
    r = valve.check(plan, STEP[ISOLATE_F1], window(lambda ps: steady(pressure=2700.0, f1_valve_pos=40.0), 80), PARAMS)
    assert r.status == S.FAIL and "did not reach" in r.message


def test_block_in_step_checks_every_target():
    # step 2 blocks in f1 then purge: purge left open must fail it
    assert run(window(lambda ps: steady(pressure=2700.0), 80)).status == S.PASS
    r = run(window(lambda ps: steady(pressure=2700.0, purge_valve_pos=100.0, purge_cmd=100.0, purge_flow=1795.0), 80))
    assert r.status == S.FAIL and "purge" in r.message
