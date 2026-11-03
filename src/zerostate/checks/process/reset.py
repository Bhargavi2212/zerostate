"""PROC-RESET: a reopened step (temporary de-isolation, e.g. inch and test) puts its points and every
step that relied on them back to pending. Before the plan can complete ({"kind": "final"} action) each
of those steps is marked again, and an isolate step is verified again by a second person after that
mark; otherwise FAIL: the isolation was broken and not shown to be back in place."""

from zerostate.models.envelope import step_targets
from zerostate.models.evidence import Finding
from zerostate.models.verdict import FindingStatus as S

RULE_ID, RULE_VERSION = "PROC-RESET", "1"
PROVING = ("vent_open", "vent_close", "hold")  # these test the isolation as a whole


def dependents(plan, k: int) -> list[int]:
    """Step k and every later step sharing one of its points or testing the isolation as a whole."""
    by_k = {s.k: s for s in plan.steps}
    points = set(step_targets(by_k[k]))
    return [s.k for s in plan.steps if s.k == k or (s.k > k and s.kind != "final" and
                                                    (s.kind in PROVING or points & set(step_targets(s))))]


def _who(name) -> str:
    return (name or "").strip().lower()


def check(plan, actions, params) -> Finding:
    kinds = {s.k: s.kind for s in plan.steps}
    marked_by, owed = {}, {}  # owed: step -> ("mark" | "verify", reopened step)
    for a in actions:
        k = a.get("k")
        if a["kind"] == "reopen":
            for j in dependents(plan, k):
                if j in marked_by:
                    owed[j] = ("mark", k)
                    del marked_by[j]
        elif a["kind"] == "mark":
            marked_by[k] = _who(a["by"])
            if k in owed:
                owed[k] = ("verify", owed[k][1]) if kinds[k] == "isolate" else None
        elif a["kind"] == "verify" and owed.get(k) and owed[k][0] == "verify" and _who(a["by"]) != marked_by.get(k):
            owed[k] = None
        owed = {j: v for j, v in owed.items() if v}
        if a["kind"] == "final" and owed:
            j, (what, r) = min(owed.items())
            done = "marked done again" if what == "mark" else "verified again by a second person"
            return Finding(rule_id=RULE_ID, rule_version=RULE_VERSION, status=S.FAIL, refs=[str(j), str(r)],
                           message=f"step {j} not {done} after step {r} was reopened")
    return Finding(rule_id=RULE_ID, rule_version=RULE_VERSION, status=S.PASS,
                   message="every step put back to pending by a reopen was done again")
