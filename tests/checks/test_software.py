from checks.plan_synth import plan, pmap
from zerostate.checks.plan import software
from zerostate.models.verdict import FindingStatus as S

CV = {"kind": "valve", "device": "control_valve", "actuation": "actuated", "normal_state": "open"}
# S -> B (a blind, listed positive) -> CV1 -> W
NODES = {"S": {"kind": "source"}, "B": {"kind": "valve", "device": "block_valve", "normal_state": "open"},
         "CV1": CV, "W": {"kind": "vessel"}}
M = pmap(NODES, "S-B B-CV1 CV1-W")


def test_pass_positive_isolation_behind_the_control_valve():
    assert software.check(plan(points=[("B", "positive"), ("CV1", "non_proved")]), M, {}).status == S.PASS


def test_fail_control_valve_alone():
    f = software.check(plan(points=[("CV1", "non_proved")]), M, {})
    assert f.status == S.FAIL and f.refs == ["CV1"]
