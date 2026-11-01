"""LIVE-QUALITY: every witness fresh and physically possible (QARTOD gross range; rate of change
and spike only on the continuous state variables pressure and level)."""

from zerostate.checks.live import finding, series
from zerostate.models.verdict import FindingStatus as S

RULE_ID = "LIVE-QUALITY"
RULE_VERSION = "2"  # v2: rate over a rate_window_process_s baseline, not one poll
CONTINUOUS = {"pressure": ("max_rate_kpa_per_process_s", "spike_kpa"),
              "level": ("max_rate_level_pct_per_process_s", "spike_level_pct")}


def _range(role, tag, window, params):
    if role == "pressure":
        return params["pressure_min_kpa"], params["pressure_max_kpa"]
    if role == "mode":
        return 0.0, 1.0
    if role == "flow":
        return window.spans.get(tag, (0.0, float("inf")))
    return 0.0, 100.0  # level, feedback, command (%)


def check(plan, step, window, params):
    unknown = []
    for w in plan.witnesses:
        s = series(window, w.signal_ref)
        if not s:
            unknown.append(f"{w.signal_ref}: no samples")
            continue
        bad_q = [q for _, _, q in s if q != "GOOD"]
        if bad_q:
            unknown.append(f"{w.signal_ref}: {bad_q[0]}")
        lo, hi = _range(w.role, w.signal_ref, window, params)
        for _ps, v, _q in s:
            if v is not None and not lo <= v <= hi:
                return finding(RULE_ID, RULE_VERSION, S.FAIL,
                               f"{w.signal_ref} = {v:.4g} is outside its physical range {lo:g}-{hi:g}", [w.signal_ref])
        if w.role in CONTINUOUS:
            rate_key, spike_key = CONTINUOUS[w.role]
            vals = [(ps, v) for ps, v, q in s if v is not None and q == "GOOD"]
            # Rate over a baseline of at least rate_window_process_s: one late poll carrying a stale value
            # (transport jitter, x10 turns 1 s into 10 process-s) must not look like an impossible change.
            j = 0
            for i, (p1, v1) in enumerate(vals):
                while j + 1 < i and p1 - vals[j + 1][0] >= params["rate_window_process_s"]:
                    j += 1
                p0, v0 = vals[j]
                if p1 - p0 >= params["rate_window_process_s"] and abs(v1 - v0) / (p1 - p0) > params[rate_key]:
                    return finding(RULE_ID, RULE_VERSION, S.FAIL,
                                   f"{w.signal_ref} changed {abs(v1 - v0):.4g} in {p1 - p0:.3g} process-s, "
                                   "faster than the process can move", [w.signal_ref])
            for (_, a), (_, b), (_, c) in zip(vals, vals[1:], vals[2:], strict=False):
                if abs(b - (a + c) / 2) - abs(c - a) / 2 > params[spike_key]:
                    return finding(RULE_ID, RULE_VERSION, S.FAIL,
                                   f"{w.signal_ref} spike ({b:.4g} between {a:.4g} and {c:.4g})", [w.signal_ref])
    if unknown:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, "instrument data not usable: " + "; ".join(unknown))
    return finding(RULE_ID, RULE_VERSION, S.PASS, "all witnesses fresh and in range")
