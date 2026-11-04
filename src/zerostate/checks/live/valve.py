"""LIVE-VALVE: commanded state, position feedback, and no flow through a valve that reads closed."""

from zerostate.checks.live import aligned, cutoff, finding, series, tag_for
from zerostate.models.envelope import step_targets
from zerostate.models.verdict import FindingStatus as S

RULE_ID = "LIVE-VALVE"
RULE_VERSION = "2"  # v2: a valve with no flow witness is checked on command + feedback (v1: always UNKNOWN)


def targets(plan, step):
    """(target, required) pairs this step checks; on the hold, every point closed before it."""
    if step.kind != "hold":
        return [(t, step.required_state) for t in step_targets(step)]
    latest = {}
    for s in plan.steps:
        if s.k < step.k and s.kind in ("isolate", "vent_close"):
            for t in step_targets(s):
                latest[t] = s.required_state
    return list(latest.items())


def check(plan, step, window, params, only=None):
    """`only`: the monitor's (target, required, settle end in process-s within this window) triples."""
    tol = params["valve_tol_pct"]
    start_all = 0.0 if step.kind == "hold" else step.settle_process_s
    pairs = only if only is not None else [(t, r, start_all) for t, r in targets(plan, step)]
    for item in pairs:
        target, req, start = (*item, 0.0)[:3]  # sessions logged before the settle end used 2-tuples
        cmd, fb, fl = (tag_for(plan, target, r) for r in ("command", "feedback", "flow"))
        if fb is None:  # a plain tag (e.g. manual_mode) must equal the required state
            vals = [v for ps, v, _ in series(window, target) if ps >= start and v is not None]
            if not vals:
                return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"no {target} samples after settle", [target])
            if any(abs(v - req) > 0.5 for v in vals):
                return finding(RULE_ID, RULE_VERSION, S.FAIL, f"commanded state wrong: {target} is not {req:g}", [target])
            continue
        # a valve without its own flow meter (most of P2's) is checked on command and feedback alone
        tags = [x for x in (cmd, fb, fl) if x is not None]
        rows = [[dict(zip(tags, vals)).get(x) for x in (cmd, fb, fl)]
                for ps, vals in aligned(window, *tags) if ps >= start]
        if not rows:
            return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"no {target} samples after settle", [cmd, fb, fl])
        for c, x, f in rows:
            if c is not None and abs(c - req) > tol:
                return finding(RULE_ID, RULE_VERSION, S.FAIL,
                               f"commanded state wrong: {cmd} = {c:.1f} %, plan needs {req:g} %", [cmd])
            if x is not None and abs(x - req) > tol:
                return finding(RULE_ID, RULE_VERSION, S.FAIL,
                               f"valve did not reach position: {fb} = {x:.1f} %, plan needs {req:g} %", [fb])
            if req <= tol and x is not None and x <= tol and f is not None and f > cutoff(window, fl, params):
                return finding(RULE_ID, RULE_VERSION, S.FAIL,
                               f"flow through a valve reading closed: {fl} = {f:.1f} while {fb} = {x:.1f} % "
                               "(passing valve or false feedback)", [fl, fb])
    return finding(RULE_ID, RULE_VERSION, S.PASS, "commanded state, position and flow agree with the plan")
