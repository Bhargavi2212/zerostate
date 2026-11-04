"""PLAN-MAPPING: every plan tag exists in the plant map, the work equipment exists, and every pressure
or level witness sits on the side the plan declares, computed from the map and the closed points
(Pemex 2024, Formosa 2004). Feedback, command and flow witnesses are tied to points by `point`, not
side-checked."""

from zerostate.checks.plan import closed_points, finding, work_node
from zerostate.graph.build import graph
from zerostate.graph.regions import sides
from zerostate.models.envelope import step_targets
from zerostate.models.verdict import FindingStatus as S

RULE_ID, RULE_VERSION = "PLAN-MAPPING", "1"


def check(plan, m, params):
    nodes = {n.id for n in m.nodes}
    at = {i.signal_ref: i.at for i in m.instruments}
    tags = [p.tag for p in plan.points] + [pp.tag for pp in plan.proving] + [t for pp in plan.proving for t in pp.proves]
    tags += [t for s in plan.steps if s.kind in ("isolate", "vent_open", "vent_close") for t in step_targets(s)]
    tags += [w.point for w in plan.witnesses if w.point]
    bad = [f"{t} is not in the plant map" for t in dict.fromkeys(tags) if t not in nodes]
    bad += [f"witness {w.signal_ref} is not in the plant map" for w in plan.witnesses if w.signal_ref not in at]
    if plan.work.equipment not in m.tags():
        bad.append(f"work equipment {plan.work.equipment} is not in the plant map")
    side = sides(graph(m), closed_points(plan), work_node(plan, m))
    bad += [f"witness {w.signal_ref} is on the {side[at[w.signal_ref]]} side, the plan says {w.side}"
            for w in plan.witnesses
            if w.role in ("pressure", "level") and w.signal_ref in at and side[at[w.signal_ref]] != w.side]
    if bad:
        return finding(RULE_ID, RULE_VERSION, S.FAIL, "; ".join(bad))
    return finding(RULE_ID, RULE_VERSION, S.PASS, "every tag is in the plant map and every gauge is on its declared side")
