"""LIVE-RELATION: pressure must agree with physics and with its redundant partner while the vent is open.

- valve_sqrt_law (P1): P_est = p_floor + (F / (k x))^2 from the vent's flow and feedback.
- valve_flow_gas (P2): F = cv x/100 sqrt(P^2 - p_floor^2), so P_est = sqrt((F / (cv x/100))^2 + p_floor^2);
  used only with the feedback at its open end stop (limit switches say nothing in travel).
- redundant_pair: two gauges within tol_pct of span.
With three estimates (two gauges + the law) it votes 2-of-3: the one that disagrees with both others is
named. A one-sided CUSUM against the law catches slow low drift."""

import math

from zerostate.checks.live import aligned, finding, tag_for
from zerostate.models.envelope import step_targets
from zerostate.models.verdict import FindingStatus as S

RULE_ID = "LIVE-RELATION"
RULE_VERSION = "2"  # v2: redundant_pair, valve_flow_gas, 2-of-3 voting; valve_sqrt_law path unchanged
WHY = "instrument wrong, or valve fouled / feedback wrong"


def check(plan, step, window, params):
    target = step_targets(step)[0] if step_targets(step) else None
    fb, fl = tag_for(plan, target, "feedback"), tag_for(plan, target, "flow")
    rel = next((r for r in plan.relations if r.type == "valve_sqrt_law" and fb in r.signals), None)
    if rel is not None:
        return _sqrt_law(plan, step, window, params, rel, fb, fl)
    law = next((r for r in plan.relations if r.type == "valve_flow_gas" and fb in r.signals and fl in r.signals), None)
    pair = next((r for r in plan.relations if r.type == "redundant_pair"), None)
    if law is None and pair is None:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"no valve law in the plan for {step.target}")
    return _vote(window, params, law, pair, fb, fl)


def _sqrt_law(plan, step, window, params, rel, fb, fl):
    p_tag = tag_for(plan, None, "pressure")
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


def _off(est, a, b, law_name, tol_kpa, floor, params) -> bool:
    """Do two estimates disagree? Gauges: beyond the pair tolerance; gauge vs law: the law's residual."""
    if law_name not in (a, b):
        return abs(est[a] - est[b]) > min(tol_kpa[a], tol_kpa[b])
    g, pl = (a, est[b]) if b == law_name else (b, est[a])
    return abs(100 * (est[g] - pl) / max(pl - floor, 1.0)) > params["relation_tol_pct"]


def _vote(window, params, law, pair, fb, fl):
    gauges = list(pair.signals) if pair else [s for s in law.signals if s not in (fb, fl)]
    tol_pct = dict(pair.params)["tol_pct"] if pair else params["relation_tol_pct"]
    tol_kpa = {g: tol_pct / 100 * (window.spans.get(g, (0.0, 0.0))[1] - window.spans.get(g, (0.0, 0.0))[0]) for g in gauges}
    law_name = f"the vent law from {fl} and {fb}"
    cv, floor = (dict(law.params)["cv"], dict(law.params)["p_floor"]) if law else (None, None)
    open_end = 100 - params["valve_tol_pct"]
    tags = gauges + ([fb, fl] if law else [])
    consec: dict[str, int] = {}
    cusum = {g: 0.0 for g in gauges}
    used = 0
    for _ps, vals in aligned(window, *tags):
        p = dict(zip(gauges, vals[:len(gauges)], strict=True))
        if any(v is None or v < params["relation_min_kpa"] for v in p.values()):
            continue
        est = dict(p)
        if law:
            x, f = vals[len(gauges):]
            if x is not None and f is not None and x >= open_end:
                p_law = math.sqrt((f / (cv * x / 100)) ** 2 + floor ** 2)
                if p_law >= params["relation_min_kpa"]:
                    est[law_name] = p_law
        if len(est) < 2:
            continue
        used += 1
        names = list(est)
        if len(names) >= 3:  # 2-of-3: the one out against both others
            bad = [n for n in names if all(_off(est, n, m, law_name, tol_kpa, floor, params) for m in names if m != n)]
        else:
            bad = ["pair"] if _off(est, *names, law_name, tol_kpa, floor, params) else []
        for key in list(consec):
            if key not in bad:
                consec[key] = 0
        for key in bad:
            consec[key] = consec.get(key, 0) + 1
            if consec[key] >= params["relation_n_consec_samples"]:
                shown = ", ".join(f"{n} {v:.0f} kPa" for n, v in est.items())
                who = (f"{' and '.join(names)} disagree" if key == "pair"
                       else f"{key} disagrees with {' and '.join(n for n in names if n != key)}")
                return finding(RULE_ID, RULE_VERSION, S.FAIL, f"{who} ({shown}): {WHY}", [*gauges, fl, fb] if law else gauges)
        if law_name in est:
            for g in gauges:
                r_pct = 100 * (p[g] - est[law_name]) / max(est[law_name] - floor, 1.0)
                cusum[g] = max(0.0, cusum[g] - r_pct - params["cusum_k_pct"])
                if cusum[g] > params["cusum_h_pct"]:
                    return finding(RULE_ID, RULE_VERSION, S.FAIL,
                                   f"{g} drifting low against {law_name} (slow drift): {WHY}", [g, fl, fb])
    if used == 0:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, "no samples with the vent open within the relation's range")
    return finding(RULE_ID, RULE_VERSION, S.PASS,
                   f"{' and '.join(gauges)} agree{' with ' + law_name if law else ''} over {used} samples")
