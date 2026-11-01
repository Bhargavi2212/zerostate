"""C11: a logged session replays to the same findings and verdicts; a changed threshold shows up."""

from checks.synth import HOLD, PARAMS, PLAN, STEP, VENT, VENT_CLOSE, steady, vent, window

from zerostate import gate
from zerostate.audit.log import AuditLog
from zerostate.audit.replay import replay
from zerostate.models.verdict import FindingStatus


def record(tmp_path):
    """Log a clean synthetic session the way session.py does: one evaluation event per step."""
    log = AuditLog(tmp_path / "audit.sqlite")
    log.append("s1", "session_start", {"plan": PLAN.model_dump(mode="json"), "plan_hash": PLAN.content_hash()})
    closed_full = (lambda ps: steady(pressure=2700.0), 80)
    traj = {1: (steady, 20), 2: closed_full, 3: closed_full, 4: closed_full, 5: closed_full,
            VENT: (vent, 120), VENT_CLOSE: (steady, 80), HOLD: (steady, 600)}
    verdict, passed = None, {}
    for k, (fn, dur) in traj.items():
        w = window(fn, dur)
        findings = gate.evaluate(PLAN, STEP[k], w, PARAMS, STEP[k].checks)
        passed[k] = gate.combine(findings) == FindingStatus.PASS
        verdict = gate.next_verdict(verdict, findings, gate.completes_plan(PLAN, passed, k))
        log.append("s1", "evaluation", {"source": "step", "step": k, "rules": list(STEP[k].checks), "only": None,
                                        "window": w.model_dump(mode="json"), "thresholds_version": PARAMS["version"],
                                        "findings": [x.model_dump(mode="json") for x in findings],
                                        "verdict_after": verdict.value if verdict else None})
    return log, verdict


def test_clean_session_replays_identically(tmp_path):
    log, verdict = record(tmp_path)
    assert verdict.value == "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"
    assert replay(log, "s1", PARAMS) == []


def test_changed_threshold_is_reported(tmp_path):
    log, _ = record(tmp_path)
    mismatches = replay(log, "s1", {**PARAMS, "alive_min_fall_pct": 99})
    assert mismatches and any("LIVE-ALIVE" in m for m in mismatches)
