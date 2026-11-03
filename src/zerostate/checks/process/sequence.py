"""PROC-SEQUENCE: steps are marked in plan order, each only after every earlier step was evaluated
(fixed step order, stop at the first failure). Reads the "mark" actions: {"kind": "mark", "k": step,
"by": name, "evaluated": [steps evaluated when it was marked]}, in the order they arrived."""

from zerostate.models.evidence import Finding
from zerostate.models.verdict import FindingStatus as S

RULE_ID, RULE_VERSION = "PROC-SEQUENCE", "1"


def check(plan, actions, params) -> Finding:
    order = [s.k for s in plan.steps if s.kind != "final"]
    for a in actions:
        if a["kind"] != "mark":
            continue
        k = a["k"]
        missing = [j for j in order[:order.index(k)] if j not in a["evaluated"]]
        if missing:
            return Finding(rule_id=RULE_ID, rule_version=RULE_VERSION, status=S.FAIL,
                           message=f"step {k} marked before step {missing[0]} was verified", refs=[str(k), str(missing[0])])
    return Finding(rule_id=RULE_ID, rule_version=RULE_VERSION, status=S.PASS,
                   message="every step marked in plan order, each after the steps before it were evaluated")
