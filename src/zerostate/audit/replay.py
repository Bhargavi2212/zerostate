"""Re-run every logged evaluation of a session from its logged window, with the current rules and
thresholds, and report any finding or verdict that comes out different."""

from zerostate import gate
from zerostate.audit.log import AuditLog
from zerostate.checks.plan import run_plan_checks
from zerostate.models.envelope import IsolationPlan
from zerostate.models.evidence import Window
from zerostate.models.plant_map import PlantMap
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
        if e["kind"] == "verdict" and p.get("source") in ("warm_in", "monitor_error"):  # not from a window
            verdict = gate.worsen(verdict, Verdict(p["verdict"]))
            continue
        if e["kind"] != "evaluation":
            continue
        if p["source"] == "plan":  # re-run on the logged map; a plan evaluation never changes the verdict
            m = PlantMap.model_validate(p["map"])
            if m.content_hash() != p["map_hash"]:
                mismatches.append(f"event {e['id']}: logged map does not match its logged hash")
            got = [(f.rule_id, f.status.value, f.message, f.path) for f in run_plan_checks(plan, m, params)]
            logged = [(f["rule_id"], f["status"], f["message"], f.get("path", [])) for f in p["findings"]]
            if got != logged:
                mismatches.append(f"event {e['id']} (plan): replay {got} != logged {logged}")
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
