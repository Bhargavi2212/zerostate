"""The with-camera verdict track. It never touches the data-only track: it reads the session's marks and
verdict, captures and reads displays in a worker thread, and logs its own events:

  camera_capture   {step, points}                         a burst was started (status: camera_pending)
  camera_reading   {step, point, value, readable, ...}    one display read; frame sha256, never the frame
  evaluation       {source: "camera", readings, previous, feedback, findings, verdict_after, with_camera_after}
  verdict          {track: "with_camera", ...stamp, models}  when the camera's contribution worsens

with-camera verdict = gate.worsen(data-only verdict, every camera contribution so far); a camera finding
can add a block (or, with `camera: required`, an escalation), never a pass.
"""

import hashlib
import io
import queue
import time
from pathlib import Path

import yaml
from PIL import Image

from zerostate import gate
from zerostate.camera.client import fetch_frame
from zerostate.camera.freeze import ahash, value_at
from zerostate.camera.locate import locate
from zerostate.camera.read import read_display
from zerostate.checks.live import camera, tag_for
from zerostate.llm.client import SAM, SPARK, ModelUnavailable, sam_boxes, spark_json
from zerostate.models.envelope import step_targets

CAMERA_KINDS = ("isolate", "vent_open", "vent_close")  # valve steps; not the hold
FRAMES, GAP_WALL_S = 3, 2.0
KEEP_WALL_S = 300
MODELS = {"locate": SAM, "read": SPARK}


def load_display_map(path: str | Path) -> dict[str, tuple[str, list]]:
    """display_map.yaml (views -> displays: {point: [x1, y1, x2, y2]}) -> {point: (view, box)}."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig")) or {}
    return {p: (view, list(box)) for view, v in (raw.get("views") or {}).items() for p, box in (v.get("displays") or {}).items()}


def burst(job: dict, fetch=fetch_frame, sam=sam_boxes, spark=spark_json, sleep=time.sleep, clock=time.monotonic) -> list[dict]:
    """Capture FRAMES frames GAP_WALL_S apart for every view the job needs, then locate and read each
    display. Never raises: a failed fetch or model call is an unreadable reading."""
    points: dict[str, tuple[str, list]] = job["points"]
    views = sorted({v for v, _ in points.values()})
    frames, t0 = [], clock()
    for i in range(FRAMES):
        if i:
            sleep(max(0.0, t0 + i * GAP_WALL_S - clock()))
        for v in views:
            try:
                frames.append((v, *fetch(v)))
            except Exception as e:  # noqa: BLE001 - no frame = unreadable reading, never a crash
                frames.append((v, None, time.time(), f"no frame: {type(e).__name__}"))
    out = {p: [] for p in points}
    for v, data, t, *err in frames:
        regions = {p: box for p, (view, box) in points.items() if view == v}
        try:
            if data is None:
                raise ValueError(err[0])
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception as e:  # noqa: BLE001
            for p in regions:
                out[p].append({"t": t, "value": None, "readable": False, "frame_sha256": None, "crop_hash": None,
                               "note": str(e) if data is None else f"bad frame: {type(e).__name__}"})
            continue
        sha = hashlib.sha256(data).hexdigest()
        try:
            boxes, note = locate(data, img.size, regions, sam), None
        except ModelUnavailable as e:
            boxes, note = dict.fromkeys(regions), f"locate unavailable: {e}"
        for p, region in regions.items():
            r = {"t": t, "value": None, "readable": False, "frame_sha256": sha, "crop_hash": ahash(img.crop(tuple(int(x) for x in region))),
                 "note": note or (None if boxes[p] else "display not located")}
            if boxes[p] is not None:
                try:
                    r.update(read_display(img, boxes[p], spark))
                except ModelUnavailable as e:
                    r["note"] = f"read unavailable: {e}"
            out[p].append(r)
    return [{"step": job["step"], "point": p, "readings": rs} for p, rs in out.items()]


def worker(jobs: queue.Queue, results: queue.Queue, **fns) -> None:
    """Thread body: one burst per job; results go back to the main loop, which alone writes the audit log."""
    while True:
        job = jobs.get()
        if job is None:
            return
        try:
            results.put(burst(job, **fns))
        except Exception as e:  # noqa: BLE001 - a pending capture must always resolve
            results.put([{"step": job["step"], "point": p, "readings": [], "error": f"{type(e).__name__}: {e}"}
                         for p in job["points"]])


class CameraTrack:
    def __init__(self, sid, plan, params, log, display_map: dict[str, tuple[str, list]], scale: float, override=None):
        self.sid, self.plan, self.params, self.log, self.scale, self.override = sid, plan, params, log, scale, override
        self.mode = plan.camera
        self.points = {p: vb for p, vb in display_map.items() if tag_for(plan, p, "feedback")}
        self.fb_tag = {p: tag_for(plan, p, "feedback") for p in self.points}
        self.fb: dict[str, list] = {t: [] for t in self.fb_tag.values()}
        self.prev: dict[str, list] = {}
        self.triggered: set[int] = set()
        self.verdict = None  # the camera's contribution so far

    def observe(self, now: float, signals: dict) -> None:
        for tag, rows in self.fb.items():
            s = signals.get(tag)
            if s is not None and s.value is not None and s.quality.value == "GOOD":
                rows.append((now, s.value))
            while rows and rows[0][0] < now - KEEP_WALL_S:
                rows.pop(0)

    def due(self, now: float, marks: dict[int, float], steps: dict) -> list[dict]:
        """Valve steps whose settle has elapsed: log a capture and return the jobs for the worker."""
        jobs = []
        for k, t_mark in sorted(marks.items()):
            st = steps[k]
            if k in self.triggered or st.kind not in CAMERA_KINDS or now < t_mark + st.settle_process_s / self.scale:
                continue
            self.triggered.add(k)
            pts = {p: self.points[p] for p in step_targets(st) if p in self.points}
            if pts:
                self.log.append(self.sid, "camera_capture", {"step": k, "points": sorted(pts)})
                jobs.append({"step": k, "points": pts})
        return jobs

    def no_service(self) -> None:
        """The plan declares a camera but no frame service is configured: one evaluation with no readings
        (UNKNOWN; escalates the with-camera track when the camera is required)."""
        self.record({"step": None, "point": None, "readings": [], "error": "no frame service configured (ZS_FRAMES_URL)"}, None)

    def record(self, res: dict, data_verdict) -> None:
        point = res["point"]
        tag = self.fb_tag.get(point) or "camera"
        rows, lag = self.fb.get(tag, []), self.params["camera_lag_max_wall_s"]
        readings = [{**r, "feedback_at": value_at(rows, r["t"])} for r in res["readings"]]
        for r in readings:
            self.log.append(self.sid, "camera_reading", {"step": res["step"], "point": point, "tag": tag, **r})
        if readings:
            t_first, t_last = min(r["t"] for r in readings), max(r["t"] for r in readings)
            feedback = [[t, v] for t, v in rows if t_first - lag < t <= t_last]
            before = [[t, v] for t, v in rows if t <= t_first - lag][-1:]
            feedback = before + feedback
        else:
            feedback = []
        previous = self.prev.get(point, [])
        f = camera.check(readings, feedback, self.params, previous, tag)
        before_v = self.verdict
        self.verdict = gate.worsen(self.verdict, camera.contribution(f.status, self.mode))
        with_cam = gate.worsen(data_verdict, self.verdict)
        self.log.append(self.sid, "evaluation", {
            "source": "camera", "step": res["step"], "point": point, "tag": tag, "rules": [camera.RULE_ID], "camera": self.mode,
            "readings": readings, "previous": previous, "feedback": feedback, "note": res.get("error"),
            "thresholds_version": self.params["version"], "models": MODELS, "findings": [f.model_dump(mode="json")],
            "verdict_after": self.verdict.value if self.verdict else None,
            "with_camera_after": with_cam.value if with_cam else None})
        if point is not None:
            self.prev[point] = [{k: r[k] for k in ("t", "crop_hash", "feedback_at")} for r in readings]
        if self.verdict != before_v:  # the camera's contribution worsened: stamp the with-camera verdict
            st = gate.stamp(with_cam, self.plan, self.params["version"], [f], self.override)
            st["rules"] = {**st["rules"], camera.RULE_ID: camera.RULE_VERSION}
            self.log.append(self.sid, "verdict", {"source": "camera", "track": "with_camera", "models": MODELS, **st})
