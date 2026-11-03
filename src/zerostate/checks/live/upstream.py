"""LIVE-UPSTREAM: during the hold, every upstream witness must stay at or above hold_test.upstream_min.
Without pressure behind the isolation a hold proves nothing (a dry test): that is UNKNOWN, never a pass.
Compares window means, never single samples."""

from zerostate.checks.live import finding, gauges
from zerostate.checks.live.hold import _means
from zerostate.models.verdict import FindingStatus as S

RULE_ID = "LIVE-UPSTREAM"
RULE_VERSION = "1"
WHY = "hold test meaningless: no pressure behind the isolation"


def check(plan, step, window, params):
    ht = plan.hold_test
    ups = gauges(plan, "upstream")
    if ht.upstream_min is None or not ups:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"{WHY} (no upstream witness or upstream_min in the plan)")
    shown = []
    for g in ups:
        m = _means(window, g, ht.hold_process_s, ht.window_process_s)
        if not m:
            return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"no {g} samples during the hold", [g])
        if min(m) < ht.upstream_min:
            return finding(RULE_ID, RULE_VERSION, S.UNKNOWN,
                           f"{WHY} ({g} fell to {min(m):.0f} kPa abs, needs {ht.upstream_min:g})", [g])
        shown.append(f"{g} stayed at or above {ht.upstream_min:g} kPa abs (lowest {min(m):.0f})")
    return finding(RULE_ID, RULE_VERSION, S.PASS, "; ".join(shown), ups)
