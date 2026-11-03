"""LIVE-HOLD: after the vent closes, pressure must not rise on any work-side gauge. Compares window
means, never single samples.

Plans that hold at residual pressure (hold_pressure_kpa_abs, P2) check only the rise at the hold, keep
every between-blocks gauge at or below p_depressurised through it (the bleed stays open), and check the
depressurised limit at the final vent instead (LIVE-HOLD listed in that step's checks)."""

from statistics import fmean

from zerostate.checks.live import finding, gauges, quality, series
from zerostate.models.verdict import FindingStatus as S

RULE_ID = "LIVE-HOLD"
RULE_VERSION = "3"  # v3: every work-side gauge; residual-pressure hold (rise only) + final-vent depressurised check


def _means(window, tag, until, width):
    """Window means of consecutive width-process-s chunks up to `until` (a last partial chunk included)."""
    p = [(ps, v) for ps, v, _ in series(window, tag) if v is not None and ps <= until]
    chunks: dict[int, list[float]] = {}
    for ps, v in p:
        chunks.setdefault(int(ps // width), []).append(v)
    return [fmean(c) for _, c in sorted(chunks.items())]


def _final_vent(plan, window, params):
    lim, out = plan.p_depressurised_kpa_abs, []
    if lim is None:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, "plan has no p_depressurised_kpa_abs")
    tail = window.t1 - window.t0
    for g in gauges(plan, "work"):
        end = [v for ps, v, _ in series(window, g)
               if v is not None and ps >= tail * window.process_time_scale - params["final_mean_process_s"]]
        if not end:
            return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"no {g} samples at the end of the final vent", [g])
        if fmean(end) > lim:
            return finding(RULE_ID, RULE_VERSION, S.FAIL,
                           f"{g} ends the final vent at {fmean(end):.1f} kPa abs, above {lim:g}", [g])
        out.append(f"{g} vented to {fmean(end):.1f} kPa abs")
    return finding(RULE_ID, RULE_VERSION, S.PASS, "; ".join(out), gauges(plan, "work"))


def check(plan, step, window, params):
    q = quality.check(plan, step, window, params)
    if q.status != S.PASS:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"hold evidence not usable ({q.message})")
    if step.kind != "hold":
        return _final_vent(plan, window, params)
    ht, residual = plan.hold_test, plan.hold_pressure_kpa_abs is not None
    limit = min(ht.max_rise_kpa, params["hold_max_rise_kpa"])  # thresholds may tighten a plan, never loosen it
    held = []
    for p_tag in gauges(plan, "work"):
        p = [(ps, v) for ps, v, _ in series(window, p_tag) if v is not None and ps <= ht.hold_process_s]
        if not p or p[-1][0] < ht.hold_process_s - ht.window_process_s:
            return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, "hold window incomplete", [p_tag])
        first = fmean(v for ps, v in p if ps <= ht.window_process_s)
        last = fmean(v for ps, v in p if ps >= p[-1][0] - ht.window_process_s)
        rise = last - first
        if rise > limit:
            return finding(RULE_ID, RULE_VERSION, S.FAIL,
                           f"{p_tag} rose {rise:.1f} kPa over the {ht.hold_process_s:g} process-s hold "
                           f"(limit {limit:g}): energy is getting back in", [p_tag])
        if not residual and plan.p_depressurised_kpa_abs is not None and last > plan.p_depressurised_kpa_abs:
            return finding(RULE_ID, RULE_VERSION, S.FAIL,
                           f"{p_tag} ends the hold at {last:.1f} kPa abs, above {plan.p_depressurised_kpa_abs:g}", [p_tag])
        held.append(f"{p_tag} held: rise {rise:+.1f} kPa, final {last:.1f} kPa abs")
    if residual and plan.p_depressurised_kpa_abs is not None:
        for g in gauges(plan, "between_blocks"):
            m = _means(window, g, ht.hold_process_s, ht.window_process_s)
            if not m:
                return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"no {g} samples during the hold", [g])
            if max(m) > plan.p_depressurised_kpa_abs:
                return finding(RULE_ID, RULE_VERSION, S.FAIL,
                               f"{g} rose to {max(m):.1f} kPa abs between the blocks during the hold "
                               f"(limit {plan.p_depressurised_kpa_abs:g} with the bleed open): the upstream block is passing", [g])
            held.append(f"{g} stayed at or below {plan.p_depressurised_kpa_abs:g} kPa abs")
    if not held:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, "no work-side pressure witness")
    return finding(RULE_ID, RULE_VERSION, S.PASS, "; ".join(held), gauges(plan, "work"))
