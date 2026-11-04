"""PLAN-TYPE: a hazardous source isolated only by non-proved points (HSG253). The points isolating a
source are the closed listed points around the region it still reaches. `proved` (including a proved
single block and bleed) and `positive` count; a source that still reaches the work is PLAN-PATHS."""

import networkx as nx

from zerostate.checks.plan import closed_points, finding
from zerostate.graph.build import graph
from zerostate.graph.regions import node, open_graph, sources
from zerostate.models.verdict import FindingStatus as S

RULE_ID, RULE_VERSION = "PLAN-TYPE", "1"


def check(plan, m, params):
    g = graph(m)
    closed = closed_points(plan)
    kind = {p.tag: p.isolation_type for p in plan.points}
    og = open_graph(g, closed)
    weak = []
    for s in sources(g):
        if not node(g, s).hazardous:
            continue
        reach = nx.node_connected_component(og, s) if s in og else {s}
        by = sorted({x for n in reach for x in g[n] if x in closed})
        if by and all(kind[x] == "non_proved" for x in by):
            weak.append(f"{s} (by {', '.join(by)})")
    if weak:
        return finding(RULE_ID, RULE_VERSION, S.FAIL, f"hazardous source isolated only by non-proved points: {'; '.join(weak)}",
                       refs=[w.split(" ")[0] for w in weak])
    return finding(RULE_ID, RULE_VERSION, S.PASS, "every hazardous source has a proved or positive isolation")
