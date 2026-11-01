"""LIVE-RELATION: pressure must agree with the vent valve law P_est = p_floor + (F / (k x))^2;
a one-sided CUSUM catches slow low drift."""

from zerostate.checks.live import aligned, finding, tag_for
from zerostate.models.verdict import FindingStatus as S

RULE_ID = "LIVE-RELATION"
RULE_VERSION = "1"
WHY = "instrument wrong, or valve fouled / feedback wrong"


def check(plan, step, window, params):
    p_tag = tag_for(plan, None, "pressure")
    fb, fl = tag_for(plan, step.target, "feedback"), tag_for(plan, step.target, "flow")
    rel = next((r for r in plan.relations if r.type == "valve_sqrt_law" and fb in r.signals), None)
    if rel is None:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"no valve law in the plan for {step.target}")
    k, floor = dict(rel.params)["k"], dict(rel.params)["p_floor"]
    consec, cusum, used = 0, 0.0, 0
    for _ps, (p, x, f) in aligned(window, p_tag, fb, fl):
        if None in (p, x, f) or x < params["relation_min_open_pct"] or p < params["relation_min_kpa"]:
            continue
        used += 1
        p_est = floor + (f / (k * x)) ** 2
        r_pct = 100 * (p - p_est) / max(p_est - floor, 1.0)
        consec = consec + 1 if abs(r_pct) > params["relation_tol_pct"] else 0
        cusum = max(0.0, cusum - r_pct - params["cusum_k_pct"])  # accumulates readings below the law
        if consec >= params["relation_n_consec_samples"]:
            return finding(RULE_ID, RULE_VERSION, S.FAIL,
                           f"{p_tag} {p:.0f} kPa vs {p_est:.0f} kPa from {fl} and {fb} "
                           f"(residual {r_pct:+.0f} %): {WHY}", [p_tag, fl, fb])
        if cusum > params["cusum_h_pct"]:
            return finding(RULE_ID, RULE_VERSION, S.FAIL,
                           f"{p_tag} drifting low against the valve law (slow drift): {WHY}", [p_tag, fl, fb])
    if used == 0:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, "no samples with the vent open within the relation's range")
    return finding(RULE_ID, RULE_VERSION, S.PASS, f"{p_tag} agrees with the vent valve law over {used} samples")
