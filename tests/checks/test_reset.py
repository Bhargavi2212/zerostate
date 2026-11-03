from checks.synth import PARAMS, PLAN
from zerostate.checks.process import reset
from zerostate.models.verdict import FindingStatus as S


def mark(k, by="op"):
    return {"kind": "mark", "k": k, "by": by, "evaluated": list(range(1, k))}


def verify(k, by="op2"):
    return {"kind": "verify", "k": k, "by": by}


REOPEN_F1 = {"kind": "reopen", "k": 2, "by": "op", "reason": "inch and test f1"}
BEFORE = [mark(1), mark(2), verify(2), mark(3), verify(3), mark(4), verify(4), REOPEN_F1]


def test_exports_id_and_version():
    assert reset.RULE_ID == "PROC-RESET" and reset.RULE_VERSION


def test_dependents_are_the_step_its_points_and_the_proving_steps():
    assert reset.dependents(PLAN, 2) == [2, 5, 6, 7]  # f1 + purge; vent, vent close and hold rely on them
    assert reset.dependents(PLAN, 4) == [4, 5, 6, 7]


def test_pass_reopened_step_done_and_verified_again():
    actions = [*BEFORE, mark(2), verify(2), *(mark(k) for k in (5, 6, 7)), {"kind": "final"}]
    assert reset.check(PLAN, actions, PARAMS).status == S.PASS


def test_fail_reopened_step_closed_again_but_not_verified_again():
    actions = [*BEFORE, mark(2), *(mark(k) for k in (5, 6, 7)), {"kind": "final"}]
    f = reset.check(PLAN, actions, PARAMS)
    assert f.status == S.FAIL and f.message == "step 2 not verified again by a second person after step 2 was reopened"
    assert reset.check(PLAN, actions[:-1], PARAMS).status == S.PASS  # only the plan completing needs it


def test_fail_verify_by_the_one_who_marked_it_again_does_not_count():
    actions = [*BEFORE, mark(2), verify(2, by="OP"), *(mark(k) for k in (5, 6, 7)), {"kind": "final"}]
    assert reset.check(PLAN, actions, PARAMS).status == S.FAIL
