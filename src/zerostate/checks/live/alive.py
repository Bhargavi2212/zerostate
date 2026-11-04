"""LIVE-ALIVE: every gauge on the vented segment must track the vent before it is trusted as evidence.
Open + no flow + no fall = blocked vent. Without a flow witness (a bleed) the vent counts as open on its
feedback alone. After the hold (P2's final vent) it is the "after" check: the gauges must follow the
fall from the hold pressure, which a frozen gauge can't."""

from statistics import fmean

from zerostate.checks.live import (
    after_hold,
    aligned,
    cutoff,
    finding,
    p_floor,
    series,
    tag_for,
    vent_gauges,
)
from zerostate.models.envelope import step_targets
from zerostate.models.verdict import FindingStatus as S

RULE_ID = "LIVE-ALIVE"
RULE_VERSION = "3"  # v3: a bleed no segment names drains the between-blocks gauges (plans merged without segments); v2: gauges by segment, floor from the plan, blocked vent FAILs, bleeds, after-hold check


def check(plan, step, window, params):
    target = step_targets(step)[0] if step_targets(step) else None
    fb, fl = tag_for(plan, target, "feedback"), tag_for(plan, target, "flow")
    horizon, open_pct, floor = params["vent_check_process_s"], params["alive_purge_open_pct"], p_floor(plan)
    if fl is not None:
        vent = [vals for ps, vals in aligned(window, fb, fl) if ps <= horizon]
        flowing = any(x is not None and f is not None and x >= open_pct and f > cutoff(window, fl, params) for x, f in vent)
        fb_open = any(x is not None and x >= open_pct for x, _ in vent)
    else:
        flowing = fb_open = any(v is not None and v >= open_pct for ps, v, _ in series(window, fb) if ps <= horizon)
    falls = {}
    for g in vent_gauges(plan, target):
        p = [v for ps, v, _ in series(window, g) if v is not None and ps <= horizon]
        if len(p) >= 5:
            p0 = fmean(p[:4])
            falls[g] = 100 * (p0 - min(p)) / max(p0 - floor, 1e-6)  # share of the starting gauge pressure
        else:
            falls[g] = None
    if not falls:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"no pressure witness on the segment {target} vents")
    if not flowing:
        if fb_open and falls and None not in falls.values() and max(falls.values()) < params["alive_min_fall_pct"]:
            return finding(RULE_ID, RULE_VERSION, S.FAIL,
                           f"vent blocked: {fb} open, {fl} at or below its cutoff and no pressure fall "
                           f"({', '.join(f'{g} {f:.1f} %' for g, f in falls.items())})", [fb, fl, *falls])
        what = f"open with flow ({fb}, {fl})" if fl is not None else f"open ({fb})"
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"vent never confirmed {what}", [fb, fl] if fl is not None else [fb])
    when = " after the hold" if after_hold(plan, step) else ""
    passed = []
    for g, fall_pct in falls.items():
        if fall_pct is None:
            return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, "too few pressure samples during the vent", [g])
        if fall_pct < params["alive_min_fall_pct"]:
            return finding(RULE_ID, RULE_VERSION, S.FAIL,
                           f"{g} fell only {fall_pct:.1f} % of gauge in {horizon:g} process-s with the vent open{when}: "
                           "the gauge is not tracking the process", [g, fb, fl])
        passed.append(f"{g} fell {fall_pct:.0f} % of gauge with the vent open{when}")
    return finding(RULE_ID, RULE_VERSION, S.PASS, "; ".join(passed), list(falls))
