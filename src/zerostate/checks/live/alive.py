"""LIVE-ALIVE: the pressure gauge must track the vent before it is trusted as evidence."""

from statistics import fmean

from zerostate.checks.live import aligned, cutoff, finding, series, tag_for
from zerostate.models.verdict import FindingStatus as S

RULE_ID = "LIVE-ALIVE"
RULE_VERSION = "1"


def check(plan, step, window, params):
    p_tag = tag_for(plan, None, "pressure")
    fb, fl = tag_for(plan, step.target, "feedback"), tag_for(plan, step.target, "flow")
    horizon = params["vent_check_process_s"]
    vent = [vals for ps, vals in aligned(window, fb, fl) if ps <= horizon]
    if not any(x is not None and f is not None and x >= params["alive_purge_open_pct"] and f > cutoff(window, fl, params)
               for x, f in vent):
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"vent never confirmed open with flow ({fb}, {fl})", [fb, fl])
    p = [v for ps, v, _ in series(window, p_tag) if v is not None and ps <= horizon]
    if len(p) < 5:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, "too few pressure samples during the vent", [p_tag])
    p0 = fmean(p[:4])
    fall_pct = 100 * (p0 - min(p)) / max(p0 - 100.0, 1e-6)  # share of the starting gauge pressure
    if fall_pct >= params["alive_min_fall_pct"]:
        return finding(RULE_ID, RULE_VERSION, S.PASS, f"{p_tag} fell {fall_pct:.0f} % of gauge with the vent open", [p_tag])
    return finding(RULE_ID, RULE_VERSION, S.FAIL,
                   f"{p_tag} fell only {fall_pct:.1f} % of gauge in {horizon:g} process-s with the vent open: "
                   "the gauge is not tracking the process", [p_tag, fb, fl])
