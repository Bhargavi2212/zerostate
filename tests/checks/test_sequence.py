from checks.synth import PARAMS, PLAN
from zerostate.checks.process import sequence
from zerostate.models.verdict import FindingStatus as S


def mark(k, evaluated, by="op"):
    return {"kind": "mark", "k": k, "by": by, "evaluated": evaluated}


def test_exports_id_and_version():
    assert sequence.RULE_ID == "PROC-SEQUENCE" and sequence.RULE_VERSION


def test_pass_each_step_after_the_previous_was_evaluated():
    actions = [mark(1, []), mark(2, [1]), mark(3, [1, 2]), mark(4, [1, 2, 3])]
    assert sequence.check(PLAN, actions, PARAMS).status == S.PASS


def test_fail_skipped_step():
    f = sequence.check(PLAN, [mark(1, []), mark(2, [1]), mark(4, [1, 2])], PARAMS)
    assert f.status == S.FAIL and f.message == "step 4 marked before step 3 was verified"


def test_fail_marked_while_previous_still_pending():
    f = sequence.check(PLAN, [mark(1, []), mark(2, [])], PARAMS)
    assert f.status == S.FAIL and f.message == "step 2 marked before step 1 was verified"
