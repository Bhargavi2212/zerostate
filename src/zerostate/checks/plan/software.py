"""PLAN-SOFTWARE: a listed closed point is an actuated control valve with no positive isolation behind
it (on its source side): the isolation relies on a control-system command (OSHA 1910.147(b), HSG253)."""

import networkx as nx

from zerostate.checks.plan import closed_points, finding, work_node
from zerostate.graph.build import graph
from zerostate.graph.regions import component, node
from zerostate.models.verdict import FindingStatus as S

RULE_ID, RULE_VERSION = "PLAN-SOFTWARE", "1"


def check(plan, m, params):
    g = graph(m)
    closed = closed_points(plan)
    work = work_node(plan, m)
    work_side = component(g, closed, work) if work else set()
    positive = {p.tag for p in plan.points if p.isolation_type == "positive" and p.tag in closed}
    bad = []
    for tag in sorted(closed):
        n = m.node(tag)
        if n is None or n.device != "control_valve" or n.actuation != "actuated":
            continue
        behind = g.subgraph([x for x in g if x not in positive | work_side | {tag}])
        if any(node(g, y).kind == "source" for nb in g[tag] if nb in behind for y in nx.node_connected_component(behind, nb)):
            bad.append(tag)
    if bad:
        return finding(RULE_ID, RULE_VERSION, S.FAIL, f"isolation relies on control-system commands: {', '.join(bad)} "
                       "are actuated control valves with no positive isolation on their source side", refs=bad)
    return finding(RULE_ID, RULE_VERSION, S.PASS, "no listed point relies on a control-system command alone")
