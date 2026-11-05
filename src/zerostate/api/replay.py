"""Replay mode (`zs api --replay <bundle_dir>`): recorded bundles (docs/BUNDLE.md, v1 or v2) as the
audit-style events the live session views read. Read-only; no lab, no key."""

import gzip
import json
from pathlib import Path


def bundle_events(b: dict) -> list[dict]:
    """Evaluation ids are the logged ones, so finding ids match the live session's."""
    sid, ev = b["episode"], []

    def add(t, kind, payload, eid=None):
        ev.append({"id": eid, "t": t, "ts": None, "session": sid, "kind": kind, "payload": payload})

    times = [e["t"] for e in b.get("evaluations", [])] + [v["t"] for v in b.get("verdicts", [])] + \
            [s["marked_t"] for s in b.get("steps", []) if s.get("marked_t")]
    t0 = min(times) if times else 0.0
    start = {"plan": b["plan"], "plan_hash": b["plan_hash"], "confirmation": b.get("confirmation"),
             "process_time_scale": b.get("process_time_scale")}
    if b.get("plan_check_override") is not None:
        start["plan_check_override"] = b["plan_check_override"]
    add(t0, "session_start", start)
    add(t0, "ready", {})
    for s in b.get("steps", []):
        if s.get("marked_t") is not None:
            add(s["marked_t"], "step_done", {"k": s["k"], "by": s.get("marked_by")})
        if s.get("verified_t") is not None:
            add(s["verified_t"], "step_verify", {"k": s["k"], "by": s.get("verified_by")})
        for r in s.get("reopened") or []:
            add(r.get("t"), "step_reopen", {"k": s["k"], "by": r.get("by"), "reason": r.get("reason"), "pending": []})
    for e in b.get("evaluations", []):
        add(e["t"], "evaluation", {k: e.get(k) for k in ("source", "step", "point", "rules", "findings", "verdict_after", "window")}, e["id"])
    for v in b.get("verdicts", []):
        add(v["t"], "verdict", {"verdict": v["verdict"], "source": v.get("source"), "reasons": v.get("reasons", []),
                                **({"track": "with_camera"} if v.get("track") == "with_camera" else {})})
    for c in b.get("camera", []):
        add(c.get("t"), "camera_reading", c)
    ev.sort(key=lambda e: e["t"] if e["t"] is not None else t0)  # stable: start and ready stay first
    return ev


def load_bundles(root: str | Path) -> dict[str, dict]:
    """{session id: {bundle, events, dir}} for every bundle.json.gz under root (dir: the bundle's folder; its
    frames/<sha256>.jpg, when present, are the camera frames the recording kept)."""
    out = {}
    for p in sorted(Path(root).rglob("bundle.json.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            b = json.load(fh)
        if b.get("bundle_version") not in ("1", "2"):
            raise ValueError(f"{p}: bundle_version {b.get('bundle_version')!r} is not 1 or 2")
        out[b["episode"]] = {"bundle": b, "events": bundle_events(b), "dir": p.parent}
    return out
