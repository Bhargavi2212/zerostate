"""PROC-INDEPENDENCE: every isolate step is verified by a second person, never by the one who marked it
done (installer != verifier). Same person -> FAIL at once; a verify still missing when the plan
completes ({"kind": "final"} action) -> UNKNOWN."""

from zerostate.models.evidence import Finding
from zerostate.models.verdict import FindingStatus as S

RULE_ID, RULE_VERSION = "PROC-INDEPENDENCE", "1"


def _who(name) -> str:
    return (name or "").strip().lower()


def _finding(status, message, refs=()) -> Finding:
    return Finding(rule_id=RULE_ID, rule_version=RULE_VERSION, status=status, message=message, refs=list(refs))


def check(plan, actions, params) -> Finding:
    marked_by = {}
    verified = set()
    for a in actions:
        if a["kind"] == "mark":
            marked_by[a["k"]] = _who(a["by"])
        elif a["kind"] == "verify":
            if _who(a["by"]) == marked_by.get(a["k"]):
                return _finding(S.FAIL, f"step {a['k']} verified by {a['by']}, the person who marked it done", [str(a["k"])])
            verified.add(a["k"])
    if any(a["kind"] == "final" for a in actions):
        missing = [str(s.k) for s in plan.steps if s.kind == "isolate" and s.k not in verified]
        if missing:
            return _finding(S.UNKNOWN, f"isolate steps not verified by a second person: {', '.join(missing)}", missing)
        return _finding(S.PASS, "every isolate step verified by a second person")
    return _finding(S.PASS, "no step verified by the person who marked it")
