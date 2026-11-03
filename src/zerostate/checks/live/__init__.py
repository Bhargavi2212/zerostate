"""Live checks: pure functions check(plan, step, window, params) -> Finding. No I/O, clock or randomness.

Times inside a window are wall seconds; every rule converts them to process seconds with the
window's process_time_scale, so thresholds in *_process_s mean the same at any time scale.
"""

from zerostate.models.envelope import IsolationPlan
from zerostate.models.evidence import Finding, Window
from zerostate.models.verdict import FindingStatus


def series(window: Window, tag: str) -> list[tuple[float, float | None, str]]:
    """(process seconds since the step mark, value, quality) for one tag."""
    return [((t - window.t0) * window.process_time_scale, v, q) for t, v, _raw, q in window.samples.get(tag, [])]


def aligned(window: Window, *tags: str) -> list[tuple[float, list[float | None]]]:
    """Polls where every tag has a sample: (process s, [values in tag order])."""
    by_t: dict[float, dict[str, float | None]] = {}
    for tag in tags:
        for t, v, _raw, _q in window.samples.get(tag, []):
            by_t.setdefault(t, {})[tag] = v
    return [((t - window.t0) * window.process_time_scale, [vals[g] for g in tags])
            for t, vals in sorted(by_t.items()) if len(vals) == len(tags)]


def tag_for(plan: IsolationPlan, point: str | None, role: str) -> str | None:
    for w in plan.witnesses:
        if w.role == role and w.point == point:
            return w.signal_ref
    return None


def gauges(plan: IsolationPlan, side: str) -> list[str]:
    """Pressure witnesses on one side of the isolation (work, upstream, between_blocks), in plan order."""
    return [w.signal_ref for w in plan.witnesses if w.role == "pressure" and w.side == side]


def vent_gauges(plan: IsolationPlan, vent: str | None) -> list[str]:
    """Pressure witnesses of the segment this vent or bleed drains; work side if no segment names it."""
    segs = {s.id for s in plan.segments if vent in s.vents}
    found = [w.signal_ref for w in plan.witnesses if w.role == "pressure" and w.segment in segs]
    return found or gauges(plan, "work")


P_FLOOR_DEFAULT_KPA = 100.0  # P1's atmosphere floor, for plans that state none


def p_floor(plan: IsolationPlan) -> float:
    """Atmosphere the vents discharge to: the plan's relation p_floor (P1 100, P2 101)."""
    return next((dict(r.params)["p_floor"] for r in plan.relations if "p_floor" in dict(r.params)), P_FLOOR_DEFAULT_KPA)


def after_hold(plan: IsolationPlan, step) -> bool:
    """A vent opened after the hold (P2's final vent from the hold pressure)."""
    return any(s.kind == "hold" and s.k < step.k for s in plan.steps)


def cutoff(window: Window, tag: str, params: dict) -> float:
    lo, hi = window.spans.get(tag, (0.0, 0.0))
    return lo + (hi - lo) * params["flow_cutoff_pct"] / 100


def finding(rule_id: str, rule_version: str, status: FindingStatus, message: str, refs=()) -> Finding:
    return Finding(rule_id=rule_id, rule_version=rule_version, status=status, message=message, refs=[r for r in refs if r is not None])


from zerostate.checks.live import (  # helpers above must be defined first
    alive,
    hold,
    quality,
    relation,
    upstream,
    valve,
)

RULES = {m.RULE_ID: m for m in (quality, alive, relation, valve, hold, upstream)}
