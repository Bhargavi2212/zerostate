"""The same process trajectory sampled at x1 and x10 gives the same verdict from every rule."""

import pytest

from checks.synth import PARAMS, PLAN, STEP, steady, vent, window
from zerostate.checks.live import RULES

CASES = [
    (5, vent, 120), (5, lambda ps: vent(ps, pressure=2700.0), 120),
    (2, lambda ps: steady(pressure=2700.0), 80), (2, lambda ps: steady(pressure=2700.0, f1_flow=640.0), 80),
    (7, lambda ps: steady(), 600), (7, lambda ps: steady(pressure=101 + 30 * ps / 600), 600),
]


@pytest.mark.parametrize(("k", "fn", "dur"), CASES)
def test_same_result_at_x1_and_x10(k, fn, dur):
    for rule_id in PLAN.steps[k - 1].checks:
        rule = RULES[rule_id]
        a = rule.check(PLAN, STEP[k], window(fn, dur, scale=1.0), PARAMS).status
        b = rule.check(PLAN, STEP[k], window(fn, dur, scale=10.0), PARAMS).status
        assert a == b, (rule_id, a, b)
