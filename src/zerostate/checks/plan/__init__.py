"""Plan checks: pure functions check(plan, plant_map, params) -> Finding, run before anyone acts.
No I/O, clock or randomness. Regions come from graph/regions.py, one helper for every rule.
"""

from zerostate.models.envelope import IsolationPlan
from zerostate.models.evidence import Finding
from zerostate.models.plant_map import PlantMap
from zerostate.models.verdict import FindingStatus


def closed_points(plan: IsolationPlan) -> set[str]:
    """Every listed point in its required state: the closed ones cut the graph."""
    return {p.tag for p in plan.points if p.required_state == "closed"}


def work_node(plan: IsolationPlan, m: PlantMap) -> str | None:
    """The map node the work is on (an instrument's `at` node), or None when the map lacks it."""
    w = plan.work.equipment
    if m.node(w):
        return w
    return next((i.at for i in m.instruments if i.tag == w), None)


def finding(rule_id: str, rule_version: str, status: FindingStatus, message: str, refs=(), path=()) -> Finding:
    return Finding(rule_id=rule_id, rule_version=rule_version, status=status, message=message,
                   refs=list(refs), path=list(path))


from zerostate.checks.plan import (  # helpers above must be defined first
    boxedin,
    liveside,
    paths,
)

PLAN_RULES = {m.RULE_ID: m for m in (paths, liveside, boxedin)}


def run_plan_checks(plan: IsolationPlan, m: PlantMap, params: dict) -> list[Finding]:
    return [rule.check(plan, m, params) for rule in PLAN_RULES.values()]
