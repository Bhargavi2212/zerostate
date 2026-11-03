"""Process checks: pure functions check(plan, actions, params) -> Finding over the logged step actions
(marks), never over signals. No I/O, clock or randomness: replay re-runs them from the logged list."""

from zerostate.checks.process import sequence

PROC_RULES = {m.RULE_ID: m for m in (sequence,)}


def run_process_checks(plan, actions: list[dict], params: dict) -> list:
    return [rule.check(plan, actions, params) for rule in PROC_RULES.values()]
