"""PLAN-PROVING: every `proved` point has a proving point, and no proving point discharges into a header
that is itself a source or pressurised (reached by a source with the proving point closed), where it
would show a pressure the isolation is not letting by (IChemE LPB 250)."""

from zerostate.checks.plan import closed_points, finding
from zerostate.graph.build import graph
from zerostate.graph.regions import energised, node
from zerostate.models.verdict import FindingStatus as S

RULE_ID, RULE_VERSION = "PLAN-PROVING", "1"


def header(discharges_to: str, m) -> str | None:
    """The map node a discharge goes to (`header:<id>`, or a bare node id); None for atmosphere/flare."""
    h = discharges_to.split(":", 1)[1] if discharges_to.startswith("header:") else discharges_to
    return h if m.node(h) else None


def check(plan, m, params):
    g = graph(m)
    closed = closed_points(plan)
    bad = []
    for p in plan.points:
        if p.isolation_type != "proved" or p.tag not in closed:
            continue
        provers = [pp for pp in plan.proving if p.tag in pp.proves]
        if not provers:
            bad.append(f"{p.tag} is listed as proved but no proving point proves it")
        for pp in provers:
            h = header(pp.discharges_to, m)
            if h and (node(g, h).kind == "source" or h in energised(g, closed | {pp.tag})):
                bad.append(f"{pp.tag} (proving {p.tag}) discharges to {h}, which is pressurised")
    if bad:
        return finding(RULE_ID, RULE_VERSION, S.FAIL, "; ".join(dict.fromkeys(bad)),
                       refs=sorted({b.split(" ")[0] for b in bad}))
    return finding(RULE_ID, RULE_VERSION, S.PASS, "every proved point has a proving point that discharges to an unpressurised place")
