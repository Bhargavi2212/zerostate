"""PLAN-PATHS: with every listed point in its required state, no source may still reach the work
(a missed line, HSG253). The finding carries the open path, source first."""

from zerostate.checks.plan import closed_points, finding, work_node
from zerostate.graph.build import graph
from zerostate.graph.regions import source_path
from zerostate.models.verdict import FindingStatus as S

RULE_ID, RULE_VERSION = "PLAN-PATHS", "1"


def check(plan, m, params):
    work = work_node(plan, m)
    if work is None:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"work equipment {plan.work.equipment} is not in the plant map")
    path = source_path(graph(m), closed_points(plan), work)
    if path:
        return finding(RULE_ID, RULE_VERSION, S.FAIL, f"open path from {path[0]} to {plan.work.equipment}: "
                       f"{' -> '.join(path)}", refs=[path[0]], path=path)
    return finding(RULE_ID, RULE_VERSION, S.PASS, f"no source reaches {plan.work.equipment} with every listed point in its required state")
