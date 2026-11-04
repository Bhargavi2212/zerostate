from checks.synth import PARAMS, PLAN
from zerostate.checks.process import independence
from zerostate.models.verdict import FindingStatus as S

ISOLATE = [s.k for s in PLAN.steps if s.kind == "isolate"]  # P1: 2, 3, 4


def actions(verifier, final=True, skip=()):
    out = [{"kind": "mark", "k": k, "by": "installer-a", "evaluated": list(range(1, k))} for k in range(1, 8)]
    out += [{"kind": "verify", "k": k, "by": verifier} for k in ISOLATE if k not in skip]
    return out + ([{"kind": "final"}] if final else [])


def test_exports_id_and_version():
    assert independence.RULE_ID == "PROC-INDEPENDENCE" and independence.RULE_VERSION


def test_pass_every_isolate_step_verified_by_a_second_person():
    assert independence.check(PLAN, actions("verifier-b"), PARAMS).status == S.PASS


def test_fail_installer_verifies_own_step():
    f = independence.check(PLAN, actions(" Installer-A "), PARAMS)  # same person, however typed
    assert f.status == S.FAIL and f.message.startswith("step 2 verified by")


def test_unknown_when_a_verify_is_missing_at_final():
    f = independence.check(PLAN, actions("verifier-b", skip=(3,)), PARAMS)
    assert f.status == S.UNKNOWN and f.refs == ["3"]
    assert independence.check(PLAN, actions("verifier-b", final=False, skip=(3,)), PARAMS).status == S.PASS
