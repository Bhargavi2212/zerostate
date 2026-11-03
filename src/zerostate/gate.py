"""Verdict policy (pure). Findings -> verdict; the verdict only gets worse on its own; only a human
signature closes a session (session.py). No model judge: no model output can produce a pass or remove a block."""

from zerostate.checks.live import RULES
from zerostate.checks.plan import PLAN_RULES
from zerostate.checks.process import PROC_RULES
from zerostate.models.envelope import IsolationPlan, Step
from zerostate.models.evidence import Finding, Window
from zerostate.models.verdict import FindingStatus, Verdict
from zerostate.version import __version__

REGISTRY = {**RULES, **PLAN_RULES, **PROC_RULES}  # every rule, live, plan and process: the versions a verdict stamp lists

# Severity order; None = no verdict yet (steps pending).
RANK = {None: 0, Verdict.NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF: 1, Verdict.ESCALATED: 2, Verdict.BLOCKED: 3}


def evaluate(plan: IsolationPlan, step: Step, window: Window, params: dict, rules, only=None) -> list[Finding]:
    """Run the named rules on one window. `only` restricts LIVE-VALVE to settled (target, required, settle end) triples."""
    out = []
    for rule_id in rules:
        rule = RULES[rule_id]
        out.append(rule.check(plan, step, window, params, only=only) if (only is not None and rule_id == "LIVE-VALVE")
                   else rule.check(plan, step, window, params))
    return out


def combine(findings: list[Finding]) -> FindingStatus:
    """FAIL beats UNKNOWN beats PASS. No findings is not a pass."""
    statuses = {f.status for f in findings}
    if FindingStatus.FAIL in statuses:
        return FindingStatus.FAIL
    if FindingStatus.UNKNOWN in statuses or not findings:
        return FindingStatus.UNKNOWN
    return FindingStatus.PASS


def verdict_for(status: FindingStatus) -> Verdict | None:
    return {FindingStatus.FAIL: Verdict.BLOCKED, FindingStatus.UNKNOWN: Verdict.ESCALATED}.get(status)


def worsen(old: Verdict | None, new: Verdict | None) -> Verdict | None:
    """Monotonic: a verdict never improves on its own."""
    return new if RANK[new] > RANK[old] else old


def next_verdict(old: Verdict | None, findings: list[Finding], completes_plan: bool = False) -> Verdict | None:
    """Verdict after one evaluation. NO_DISCREPANCY only when the last checked step passes and every
    earlier step passed (completes_plan); never better than the verdict before."""
    v = verdict_for(combine(findings))
    if v is None and completes_plan:
        v = Verdict.NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF
    return worsen(old, v)


def completes_plan(plan: IsolationPlan, step_passed: dict[int, bool], k: int) -> bool:
    """True when step k is the last step before the final step and every non-final step has passed."""
    nxt = next((s for s in plan.steps if s.k == k + 1), None)
    return (nxt is not None and nxt.kind == "final"
            and all(step_passed.get(s.k) for s in plan.steps if s.kind != "final"))


def stamp(verdict: Verdict, plan: IsolationPlan, thresholds_version: str, findings: list[Finding],
          override: str | None = None) -> dict:
    """Everything a reader needs to reproduce and trust this verdict, including a plan-check override."""
    out = {
        "verdict": verdict.value,
        "package_version": __version__,
        "rules": {rid: m.RULE_VERSION for rid, m in REGISTRY.items()},
        "thresholds_version": thresholds_version,
        "plan_hash": plan.content_hash(),
        "assumptions": [a.text for a in plan.assumptions],
        "reasons": [f"{f.rule_id}: {f.message}" for f in findings if f.status != FindingStatus.PASS],
    }
    if override is not None:
        out["plan_check_override"] = override
    return out
