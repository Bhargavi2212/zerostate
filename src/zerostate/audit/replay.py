"""Re-run every logged evaluation of a session from its logged window, with the current rules and
thresholds, and report any finding or verdict that comes out different."""

from zerostate import gate
from zerostate.audit.log import AuditLog
from zerostate.models.envelope import IsolationPlan
from zerostate.models.evidence import Window
from zerostate.models.verdict import FindingStatus, Verdict


def replay(log: AuditLog, session: str, params: dict) -> list[str]:
    events = log.events(session)
    start = next((e for e in events if e["kind"] == "session_start"), None)
    if start is None:
        return [f"{session}: no session_start event"]
    plan = IsolationPlan.model_validate(start["payload"]["plan"])
    mismatches = []
    if plan.content_hash() != start["payload"]["plan_hash"]:
        mismatches.append("logged plan does not match its logged hash")
    steps = {s.k: s for s in plan.steps}
    verdict, step_passed = None, {}
    for e in events:
        p = e["payload"]
        if e["kind"] == "verdict" and p.get("source") == "warm_in":  # time-based, not from a window
            verdict = gate.worsen(verdict, Verdict(p["verdict"]))
            continue
        if e["kind"] != "evaluation":
            continue
        only = [tuple(x) for x in p["only"]] if p.get("only") is not None else None
        findings = gate.evaluate(plan, steps[p["step"]], Window.model_validate(p["window"]), params, p["rules"], only)
        got = [(f.rule_id, f.status.value, f.message) for f in findings]
        logged = [(f["rule_id"], f["status"], f["message"]) for f in p["findings"]]
        if got != logged:
            mismatches.append(f"event {e['id']} (step {p['step']}, {p['source']}): replay {got} != logged {logged}")
        done = False
        if p["source"] == "step":
            step_passed[p["step"]] = gate.combine(findings) == FindingStatus.PASS
            done = gate.completes_plan(plan, step_passed, p["step"])
        verdict = gate.next_verdict(verdict, findings, done)
        if (verdict.value if verdict else None) != p.get("verdict_after"):
            mismatches.append(f"event {e['id']}: replay verdict {verdict} != logged {p.get('verdict_after')}")
    return mismatches
