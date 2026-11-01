"""LIVE-HOLD: after the vent closes, pressure must not rise. Compares window means, never single samples."""

from statistics import fmean

from zerostate.checks.live import finding, quality, series, tag_for
from zerostate.models.verdict import FindingStatus as S

RULE_ID = "LIVE-HOLD"
RULE_VERSION = "1"


def check(plan, step, window, params):
    q = quality.check(plan, step, window, params)
    if q.status != S.PASS:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"hold evidence not usable ({q.message})")
    ht, p_tag = plan.hold_test, tag_for(plan, None, "pressure")
    p = [(ps, v) for ps, v, _ in series(window, p_tag) if v is not None and ps <= ht.hold_process_s]
    if not p or p[-1][0] < ht.hold_process_s - ht.window_process_s:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, "hold window incomplete", [p_tag])
    first = fmean(v for ps, v in p if ps <= ht.window_process_s)
    last = fmean(v for ps, v in p if ps >= p[-1][0] - ht.window_process_s)
    rise = last - first
    if rise > ht.max_rise_kpa:
        return finding(RULE_ID, RULE_VERSION, S.FAIL,
                       f"{p_tag} rose {rise:.1f} kPa over the {ht.hold_process_s:g} process-s hold "
                       f"(limit {ht.max_rise_kpa:g}): energy is getting back in", [p_tag])
    if plan.p_depressurised_kpa_abs is not None and last > plan.p_depressurised_kpa_abs:
        return finding(RULE_ID, RULE_VERSION, S.FAIL,
                       f"{p_tag} ends the hold at {last:.1f} kPa abs, above {plan.p_depressurised_kpa_abs:g}", [p_tag])
    return finding(RULE_ID, RULE_VERSION, S.PASS,
                   f"{p_tag} held: rise {rise:+.1f} kPa, final {last:.1f} kPa abs", [p_tag])
