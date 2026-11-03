"""Session lifecycle: warming_in -> ready -> steps (pending -> evaluated) -> verdict, plus the continuous
monitor. Decisions come from gate.py; every evaluation is logged with its window so it replays.

Session.tick() takes the clock as an argument, so tests drive it without sleeping. Human and operator
actions arrive through the Inbox (a separate SQLite file the core only reads); only the core writes
the audit log.
"""

import json
import sqlite3
from pathlib import Path

from zerostate import gate
from zerostate.audit.log import AuditLog
from zerostate.checks.plan import PLAN_RULES, run_plan_checks
from zerostate.models.envelope import IsolationPlan, step_targets
from zerostate.models.evidence import Window
from zerostate.models.plant_map import PlantMap
from zerostate.models.signal import Quality, Signal
from zerostate.models.verdict import FindingStatus, Verdict

TERMINAL = (Verdict.BLOCKED, Verdict.ESCALATED)


class PlanHashMismatch(Exception):
    """The plan given is not the plan a person confirmed: refuse to start."""


class PlanCheckFailed(Exception):
    """A plan check did not pass and no override was given: refuse to start."""


class Inbox:
    """Step marks, signatures and stop requests, written by `zs` commands and read by the core."""

    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path), isolation_level=None, timeout=10)
        self.db.execute("CREATE TABLE IF NOT EXISTS inbox (id INTEGER PRIMARY KEY, session TEXT, kind TEXT, payload_json TEXT)")
        self.seen = 0

    def put(self, session: str, kind: str, **payload) -> None:
        self.db.execute("INSERT INTO inbox (session, kind, payload_json) VALUES (?,?,?)", (session, kind, json.dumps(payload)))

    def take(self, session: str) -> list[dict]:
        rows = self.db.execute("SELECT id, kind, payload_json FROM inbox WHERE session = ? AND id > ? ORDER BY id",
                               (session, self.seen)).fetchall()
        if rows:
            self.seen = rows[-1][0]
        return [{"kind": k, **json.loads(p)} for _, k, p in rows]


class Session:
    def __init__(self, sid: str, plan: IsolationPlan, plan_hash: str, params: dict, process_time_scale: float,
                 spans: dict, log: AuditLog, now: float, plant_map: PlantMap | None = None, override: str | None = None,
                 confirmation: dict | None = None):
        """plant_map: run the plan checks first; any finding that is not PASS refuses the start unless an
        override text is given, which is then logged and stamped into every verdict (it never changes one).
        confirmation: the record of the person who confirmed this plan (logged at session start)."""
        if plan.content_hash() != plan_hash:
            raise PlanHashMismatch(f"plan hash {plan.content_hash()} != confirmed {plan_hash}")
        plan_findings = run_plan_checks(plan, plant_map, params) if plant_map is not None else None
        bad = [f"{f.rule_id}: {f.message}" for f in plan_findings or [] if f.status != FindingStatus.PASS]
        if bad and override is None:
            raise PlanCheckFailed("; ".join(bad))
        self.override = override
        self.sid, self.plan, self.params, self.scale, self.spans, self.log = sid, plan, params, process_time_scale, spans, log
        self.steps = {s.k: s for s in plan.steps}
        self.witnesses = {w.signal_ref for w in plan.witnesses}
        # the monitor starts at the first isolate mark (P1 step 2, P2 step 1)
        self.monitor_from = min((s.k for s in plan.steps if s.kind == "isolate"), default=float("inf"))
        self.t_start = now
        self.state = "warming_in"
        self.verdict: Verdict | None = None
        self.camera_verdict: Verdict | None = None  # set by the with-camera track (cli.py); only recorded at signing
        self.closed = self.stopped = False
        self.buffer: dict[str, list] = {t: [] for t in self.witnesses}
        self.latest: dict[str, Signal] = {}
        self.marks: dict[int, float] = {}
        self.evaluated: dict[int, FindingStatus] = {}
        self.unknown_since: float | None = None
        self.last_monitor = now
        versions = gate.stamp(Verdict.ESCALATED, plan, params["version"], [])
        start = {"plan": plan.model_dump(mode="json"), "plan_hash": plan_hash,
                 "package_version": versions["package_version"], "rules": versions["rules"],
                 "thresholds_version": params["version"], "thresholds": params, "process_time_scale": process_time_scale,
                 "confirmation": confirmation}
        if override is not None:
            start["plan_check_override"] = override
        log.append(sid, "session_start", start)
        if plan_findings is not None:  # logged with its map so replay re-runs it; never changes the verdict
            log.append(sid, "evaluation", {
                "source": "plan", "step": None, "rules": list(PLAN_RULES), "map": plant_map.model_dump(mode="json"),
                "map_hash": plant_map.content_hash(), "override": override, "thresholds_version": params["version"],
                "findings": [f.model_dump(mode="json") for f in plan_findings], "verdict_after": None})

    # ---- helpers ---------------------------------------------------------------------------
    def _ps(self, t0: float, t1: float) -> float:
        return (t1 - t0) * self.scale

    def _window(self, t0: float, t1: float) -> Window:
        samples = {tag: [s for s in rows if t0 <= s[0] <= t1] for tag, rows in self.buffer.items()}
        return Window(t0=t0, t1=t1, process_time_scale=self.scale, samples=samples, spans=self.spans)

    def _duration_ps(self, step) -> float:
        p = self.params
        if step.kind == "hold":
            return self.plan.hold_test.hold_process_s
        base = step.settle_process_s + p["valve_check_process_s"]
        return max(base, p["vent_check_process_s"]) if step.kind == "vent_open" else base

    def _next_step(self) -> int | None:
        todo = [k for k, s in sorted(self.steps.items()) if s.kind != "final" and k not in self.marks]
        return todo[0] if todo else None

    def _set_verdict(self, new: Verdict | None, findings, source: str) -> None:
        if new is not None and new != self.verdict:
            self.verdict = new
            self.log.append(self.sid, "verdict", {"source": source, **gate.stamp(new, self.plan, self.params["version"], findings, self.override)})

    def _record_evaluation(self, source: str, k: int, rules, window: Window, findings, only=None, completes=False):
        new = gate.next_verdict(self.verdict, findings, completes)
        self.log.append(self.sid, "evaluation", {
            "source": source, "step": k, "rules": list(rules), "only": only, "window": window.model_dump(mode="json"),
            "thresholds_version": self.params["version"], "findings": [f.model_dump(mode="json") for f in findings],
            "verdict_after": new.value if new else None})
        self._set_verdict(new, findings, source)

    # ---- the tick ------------------------------------------------------------------------------
    def tick(self, now: float, signals: dict[str, Signal], inbox: list[dict]) -> None:
        if self.closed or self.stopped:
            return
        for tag, s in signals.items():
            if tag in self.witnesses:
                self.buffer[tag].append((now, s.value, s.raw, s.quality.value))
                self.latest[tag] = s
        for msg in inbox:
            self._handle(now, msg)
            if self.closed or self.stopped:
                return
        if self.state == "warming_in":
            self._warm_in(now)
        if self.state == "ready":
            self._evaluate_due_steps(now)
            if any(k >= self.monitor_from for k in self.marks) and now - self.last_monitor >= self.params["monitor_period_wall_s"]:
                self._monitor(now)
                self._prune()

    def _prune(self) -> None:
        """Keep only what a pending step evaluation or the next monitor window can still need:
        a session stays open until someone signs, possibly a whole shift."""
        keep = [self.last_monitor - self.params["rate_window_process_s"] / self.scale]
        keep += [t for k, t in self.marks.items() if k not in self.evaluated]
        cutoff = min(keep)
        for tag, rows in self.buffer.items():
            if rows and rows[0][0] < cutoff:
                self.buffer[tag] = [r for r in rows if r[0] >= cutoff]

    def fail(self, reason: str) -> None:
        """The monitor itself stopped: say so in the audit log rather than go quiet."""
        self.verdict = gate.worsen(self.verdict, Verdict.ESCALATED)
        self.log.append(self.sid, "verdict", {"source": "monitor_error",
                                              **gate.stamp(Verdict.ESCALATED, self.plan, self.params["version"], [], self.override),
                                              "reasons": [f"monitor stopped: {reason}"]})

    def _warm_in(self, now: float) -> None:
        if self.witnesses <= set(self.latest) and all(self.latest[t].quality == Quality.GOOD for t in self.witnesses):
            self.state = "ready"
            self.log.append(self.sid, "ready", {"after_wall_s": round(now - self.t_start, 3)})
        elif now - self.t_start > self.params["warm_in_timeout_wall_s"]:
            self.state = "warm_in_failed"
            bad = sorted(t for t in self.witnesses if t not in self.latest or self.latest[t].quality != Quality.GOOD)
            self.verdict = Verdict.ESCALATED
            self.log.append(self.sid, "verdict", {"source": "warm_in", **gate.stamp(Verdict.ESCALATED, self.plan, self.params["version"], [], self.override),
                                                  "reasons": [f"instruments not verified live: {', '.join(bad)}"]})

    def _handle(self, now: float, msg: dict) -> None:
        kind = msg["kind"]
        if kind == "step_done":
            k, why = int(msg["k"]), None
            if self.state != "ready":
                why = f"session is {self.state}"
            elif self.verdict in TERMINAL:
                why = f"verdict is already {self.verdict.value}"
            elif any(m not in self.evaluated for m in self.marks):
                why = "previous step not evaluated yet"
            elif k != self._next_step():
                why = f"next step is {self._next_step()}"
            if why:
                self.log.append(self.sid, "step_refused", {"k": k, "by": msg.get("by"), "reason": why})
            else:
                self.marks[k] = now
                self.log.append(self.sid, "step_done", {"k": k, "by": msg.get("by")})
        elif kind == "sign":
            self.closed = True  # only a human signature closes a session
            with_cam = gate.worsen(self.verdict, self.camera_verdict)
            self.log.append(self.sid, "signature", {"by": msg.get("by"), "role": msg.get("role"), "note": msg.get("note"),
                                                    "verdict_at_signing": self.verdict.value if self.verdict else None,
                                                    "verdict_with_camera_at_signing": with_cam.value if with_cam else None})
        elif kind == "stop":
            self.stopped = True
            self.log.append(self.sid, "session_stopped", {"by": msg.get("by"), "signed": False,
                                                          "verdict": self.verdict.value if self.verdict else None})

    def _evaluate_due_steps(self, now: float) -> None:
        for k, t_mark in sorted(self.marks.items()):
            step = self.steps[k]
            if k in self.evaluated or self._ps(t_mark, now) < self._duration_ps(step):
                continue
            window = self._window(t_mark, now)
            findings = gate.evaluate(self.plan, step, window, self.params, step.checks)
            self.evaluated[k] = gate.combine(findings)
            passed = {j: st == FindingStatus.PASS for j, st in self.evaluated.items()}
            done = gate.completes_plan(self.plan, passed, k)
            self._record_evaluation("step", k, step.checks, window, findings, completes=done)
            if done:  # the final step needs no mark: it is "every step above passed"
                final = next(s.k for s in self.plan.steps if s.kind == "final")
                self.evaluated[final] = FindingStatus.PASS

    def _settled_points(self, now: float, t0: float) -> list[tuple[str, float, float]]:
        """(target, required, settle end in process-s from t0) for every point closed and settled by now."""
        latest: dict[str, tuple[float, float, float]] = {}
        for k, t_mark in sorted(self.marks.items()):
            s = self.steps[k]
            if s.kind in ("isolate", "vent_open", "vent_close"):
                for t in step_targets(s):
                    latest[t] = (t_mark, s.settle_process_s, s.required_state)
        return [(target, req, max(0.0, self._ps(t0, t_mark) + settle))
                for target, (t_mark, settle, req) in latest.items()
                if req <= self.params["valve_tol_pct"] and self._ps(t_mark, now) >= settle]

    def _monitor(self, now: float) -> None:
        # Reach back the QUALITY rate baseline too, or the rate test never has a long enough span here.
        t0 = self.last_monitor - self.params["rate_window_process_s"] / self.scale
        window = self._window(t0, now)
        self.last_monitor = now
        k = max(self.marks)
        only = self._settled_points(now, t0)
        rules = ["LIVE-QUALITY", "LIVE-VALVE"] if only else ["LIVE-QUALITY"]
        findings = gate.evaluate(self.plan, self.steps[k], window, self.params, rules, only=only if only else None)
        status = gate.combine(findings)
        if status == FindingStatus.FAIL:
            self._record_evaluation("monitor", k, rules, window, findings, only=only or None)
        elif status == FindingStatus.UNKNOWN:
            self.unknown_since = self.unknown_since or now
            if now - self.unknown_since > self.params["monitor_unknown_grace_wall_s"] and self.verdict not in TERMINAL:
                self._record_evaluation("monitor", k, rules, window, findings, only=only or None)
        else:
            self.unknown_since = None


def status_from_events(events: list[dict]) -> dict:
    """What `zs status` shows, derived only from the audit log. `verdict` is the data-only track;
    `verdict_with_camera` worsens it by the camera's own verdict events (track with_camera), if any."""
    out = {"state": "warming_in", "steps": {}, "verdict": None, "stamp": None, "refused": [],
           "verdict_with_camera": None, "camera_pending": 0}
    camera = None
    for e in events:
        p, kind = e["payload"], e["kind"]
        if kind == "ready":
            out["state"] = "ready"
        elif kind == "step_done":
            out["steps"][p["k"]] = "pending"
        elif kind == "step_refused":
            out["refused"].append(p)
        elif kind == "evaluation" and p["source"] == "step":
            st = [f["status"] for f in p["findings"]]
            out["steps"][p["step"]] = "FAIL" if "FAIL" in st else "UNKNOWN" if ("UNKNOWN" in st or not st) else "PASS"
        elif kind == "verdict" and p.get("track") == "with_camera":
            camera, out["stamp_with_camera"] = p["verdict"], p
        elif kind == "verdict":
            out["verdict"], out["stamp"] = p["verdict"], p
        elif kind == "camera_capture":
            out["camera_pending"] += len(p["points"])
        elif kind == "evaluation" and p["source"] == "camera" and p.get("step") is not None:
            out["camera_pending"] -= 1
        elif kind == "signature":
            out["state"] = "closed"
            out["signature"] = p
        elif kind == "session_stopped":
            out["state"] = "stopped"
    if out["verdict"] == Verdict.NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF.value:
        start = next(e for e in events if e["kind"] == "session_start")
        final = next(s["k"] for s in start["payload"]["plan"]["steps"] if s["kind"] == "final")
        out["steps"][final] = "PASS"
    with_cam = gate.worsen(Verdict(out["verdict"]) if out["verdict"] else None, Verdict(camera) if camera else None)
    out["verdict_with_camera"] = with_cam.value if with_cam else None
    return out
