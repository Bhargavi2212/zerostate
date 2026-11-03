from checks.plan_synth import LINE, VALVE, plan, pmap
from zerostate.checks.plan import liveside
from zerostate.models.verdict import FindingStatus as S

ACT = pmap({"S": {"kind": "source"}, "V1": VALVE, "W": {"kind": "vessel"}}, "S-V1 V1-W",
           [{"tag": "V1.CMD", "signal_ref": "V1.CMD", "role": "command", "at": "V1", "point": "V1"}])


def test_pass_work_beyond_the_device():
    assert liveside.check(plan(points=[("V1", "proved")]), LINE, {}).status == S.PASS


def test_fail_work_on_the_listed_device():
    f = liveside.check(plan(work="V1", points=[("V1", "proved")]), LINE, {})
    assert f.status == S.FAIL and "the work is on V1" in f.message


def test_fail_work_inside_the_device_boundary():
    f = liveside.check(plan(work="V1.CMD", points=[("V1", "proved")]), ACT, {})
    assert f.status == S.FAIL and "inside the boundary of listed isolation device V1" in f.message
