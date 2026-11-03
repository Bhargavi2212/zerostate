"""PLAN-BOXEDIN: the isolated region around the work holds a heater and has no way out: no relief
(a relief valve counts even when closed: it opens on pressure) and no vent or bleed to atmosphere or
flare that is open during the hold (Williams 2013)."""

from zerostate.checks.plan import closed_points, finding, work_node
from zerostate.graph.build import graph
from zerostate.graph.regions import SINK_TARGETS, component, node
from zerostate.models.envelope import step_targets
from zerostate.models.verdict import FindingStatus as S

RULE_ID, RULE_VERSION = "PLAN-BOXEDIN", "1"


def states_at_hold(plan, m) -> dict[str, str]:
    """open/closed of every valve-like node during the hold: normal state, then the steps before it."""
    state = {n.id: n.normal_state for n in m.nodes if n.normal_state}
    for s in plan.steps:
        if s.kind == "hold":
            break
        for t in step_targets(s):
            if s.kind in ("isolate", "vent_close"):
                state[t] = "closed"
            elif s.kind == "vent_open":
                state[t] = "open"
    return state


def check(plan, m, params):
    work = work_node(plan, m)
    if work is None:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"work equipment {plan.work.equipment} is not in the plant map")
    g = graph(m)
    region = component(g, closed_points(plan), work)
    heaters = sorted(n for n in region if node(g, n).kind == "heater")
    if not heaters:
        return finding(RULE_ID, RULE_VERSION, S.PASS, f"no heat source in the isolated region around {plan.work.equipment}")
    state = states_at_hold(plan, m)

    def way_out(x):
        d = node(g, x)
        return d.discharges_to in SINK_TARGETS and (d.kind == "relief" or (d.kind in ("vent", "bleed") and state.get(x) == "open"))

    exits = sorted({x for n in region for x in g[n] if x not in region and way_out(x)})
    if exits:
        return finding(RULE_ID, RULE_VERSION, S.PASS, f"{', '.join(heaters)} can relieve through {', '.join(exits)}")
    return finding(RULE_ID, RULE_VERSION, S.FAIL, f"{', '.join(heaters)} can heat the isolated region around "
                   f"{plan.work.equipment} with no relief or open vent to atmosphere or flare", refs=heaters, path=sorted(region))
