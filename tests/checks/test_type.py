from checks.plan_synth import LINE, plan
from zerostate.checks.plan import type as plan_type
from zerostate.models.verdict import FindingStatus as S


def test_pass_proved_single_block_and_bleed():
    assert plan_type.check(plan(points=[("V1", "proved")]), LINE, {}).status == S.PASS


def test_pass_positive():
    assert plan_type.check(plan(points=[("V1", "positive")]), LINE, {}).status == S.PASS


def test_fail_hazardous_source_behind_non_proved_only():
    f = plan_type.check(plan(points=[("V1", "non_proved")]), LINE, {})
    assert f.status == S.FAIL and f.refs == ["S"] and "S (by V1)" in f.message
