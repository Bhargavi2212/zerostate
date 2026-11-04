"""LIVE-CAMERA: the valve's own display, read from camera frames, agrees with its position feedback.

Pure, over logged readings and the logged feedback window, so replay re-runs it. It feeds only the
with-camera verdict track (camera/track.py); it is not in gate.RULES, so data-only verdicts never see it.

readings: [{t, value, readable, crop_hash, feedback_at, ...}] of one display over one burst (3 frames).
previous: the same display's readings from its previous burst (for the freeze check).
feedback: [[t, value]] GOOD feedback samples from (first capture - lag) to the last capture, with the
value in force at (first capture - lag) first.
"""

from zerostate.camera.freeze import frozen
from zerostate.checks.live import finding
from zerostate.models.evidence import Finding
from zerostate.models.verdict import FindingStatus as S
from zerostate.models.verdict import Verdict

RULE_ID = "LIVE-CAMERA"
RULE_VERSION = "2"  # v2: 2-of-3 majority, symmetric (v1: any agreeing frame passed)
MIN_READABLE = 2  # frames needed to agree for PASS, or to disagree for FAIL


def in_window(feedback: list, t: float, lag_s: float) -> list[float]:
    """Feedback values the display may show at capture time t: the one in force at t - lag, and every later one up to t."""
    before = [v for ft, v in feedback if ft <= t - lag_s]
    return before[-1:] + [v for ft, v in feedback if t - lag_s < ft <= t]


def check(readings: list[dict], feedback: list, params: dict, previous: list[dict] = (), tag: str = "") -> Finding:
    lag, tol = params["camera_lag_max_wall_s"], params["camera_agree_pct"]
    feedback = sorted((float(t), float(v)) for t, v in feedback)
    reason = frozen([*previous, *readings], feedback, lag, params["camera_freeze_same_pct"], tol)
    if reason:
        return finding(RULE_ID, RULE_VERSION, S.FAIL, f"{tag}: {reason}", [tag])
    readable = [r for r in readings if r.get("readable") and r.get("value") is not None]
    if len(readable) < MIN_READABLE:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN,
                       f"{tag}: {len(readable)} readable frames of {len(readings)} (need {MIN_READABLE})", [tag])
    windows = [(r["value"], w) for r in readable if (w := in_window(feedback, r["t"], lag))]
    if not windows:
        return finding(RULE_ID, RULE_VERSION, S.UNKNOWN, f"{tag}: no feedback samples at the capture times", [tag])
    # v2: majority, symmetric. One frame matching the PLC can no longer hide two that do not (v1 passed on any).
    agree = [(x, w) for x, w in windows if any(abs(x - v) <= tol for v in w)]
    disagree = [(x, w) for x, w in windows if (x, w) not in agree]
    if len(agree) >= MIN_READABLE:
        return finding(RULE_ID, RULE_VERSION, S.PASS, f"{tag}: camera agrees with the feedback in {len(agree)} of {len(windows)} frames", [tag])
    if len(disagree) >= MIN_READABLE:
        x, w = disagree[0]
        return finding(RULE_ID, RULE_VERSION, S.FAIL, f"camera shows {x:g} % while the instrument says {w[-1]:.1f} % "
                       f"in {len(disagree)} of {len(windows)} frames ({tag})", [tag])
    return finding(RULE_ID, RULE_VERSION, S.UNKNOWN,
                   f"{tag}: frames split ({len(agree)} agree, {len(disagree)} disagree of {len(windows)})", [tag])


def contribution(status: S, mode: str | None) -> Verdict | None:
    """What one camera finding adds to the with-camera track: FAIL blocks it; UNKNOWN escalates it only
    when the plan requires the camera (optional: logged and ignored); PASS adds nothing (never a pass)."""
    if status == S.FAIL:
        return Verdict.BLOCKED
    if status == S.UNKNOWN and mode == "required":
        return Verdict.ESCALATED
    return None
