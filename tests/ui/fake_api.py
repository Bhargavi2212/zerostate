"""Fixture server for the console's Playwright tests (P3-3), until replay mode (`zs api --replay`) lands.

- Plans, drafts and confirm: the real `zerostate.api.server` app on a throwaway data dir, with a fake
  model transport (never the Meta API).
- Sessions: shaped as docs/API.md `SessionDetail` (v2), built from recorded benchmark episodes
  (eval/results/bench/p1/*/audit_export.json); the stream replays their logged events, then ends.
- Writes (done / verify / sign / session start) only append to <data>/inbox.jsonl in the throwaway dir.
  Like the API, a sign by `playwright-test` is refused (403) when the data dir is the real /data.
"""

import copy
import io
import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from zerostate.api import server

ROOT = Path(__file__).parents[2]
BENCH = ROOT / "eval/results/bench/p1"
BLOCKED_EP = "S4-small_seed1318434843_20261103T035803"
OVERRIDE = "control-valve isolation accepted for live-evidence testbed"
TEST_NAME = "playwright-test"
TRANSCRIPT = "Job F-210. XV-201 closed proved seq 1. XV-203 closed seq 2. BV-202 open seq 3. XV-204 closed proved seq 4. Vent VV-213."
LIST_REPLY = {"plant": "p2_gasline", "work_equipment": "F-210", "vent": "VV-213", "hold_minutes": None,
              "points": [{"tag": "XV-201", "required_state": "closed", "seq": 1, "isolation_type": "proved"},
                         {"tag": "XV-203", "required_state": "closed", "seq": 2, "isolation_type": None},
                         {"tag": "BV-202", "required_state": "open", "seq": 3},
                         {"tag": "XV-204", "required_state": "closed", "seq": 4, "isolation_type": "proved"}],
              "proving": [{"tag": "BV-202", "proves": ["XV-201", "XV-203"]}, {"tag": "VV-213", "proves": ["XV-204"]}]}


class FakeOpener:
    """Model transport stand-in: a sheet transcript for image requests, else the draft list above
    (XV-203's isolation type left unclear, hold time left to the plant default)."""

    def open(self, req, timeout=None):
        body = json.loads(req.data)
        image = any(isinstance(m["content"], list) for m in body["messages"])
        content = json.dumps({"text": TRANSCRIPT} if image else LIST_REPLY)
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}],
                                      "usage": {"prompt_tokens": 10, "completion_tokens": 10}}).encode())


def wall(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


def episode(folder: Path) -> tuple[dict, list[tuple[str, dict]]]:
    """A recorded episode -> (SessionDetail, stream events)."""
    ev = json.loads((folder / "audit_export.json").read_text(encoding="utf-8"))
    start = next(e for e in ev if e["kind"] == "session_start")
    plan = start["payload"]["plan"]
    steps = [{"k": s["k"], "kind": s["kind"], "targets": s["targets"] or ([s["target"]] if s["target"] else []),
              "required_state": s["required_state"], "marked_by": None, "marked_t": None, "verified_by": None,
              "verified_t": None, "reopened": [], "result": None, "finding_ids": []} for s in plan["steps"]]
    by_k = {s["k"]: s for s in steps}
    findings, stream, data_only = [], [], None
    for e in ev:
        p, kind = e["payload"], e["kind"]
        if kind == "step_done":
            by_k[p["k"]].update(marked_by=p["by"], marked_t=wall(e["ts"]))
        elif kind == "evaluation":
            for f in p["findings"]:
                f = {"path": [], **f, "id": f"{e['id']}:{f['rule_id']}", "eval_id": e["id"], "source": p["source"],
                     "step": p.get("step"), "t": wall(e["ts"])}
                findings.append(f)
                if p["source"] == "step":
                    by_k[p["step"]]["finding_ids"].append(f["id"])
            if p["source"] == "step":
                sts = [f["status"] for f in p["findings"]]
                by_k[p["step"]]["result"] = "FAIL" if "FAIL" in sts else "UNKNOWN" if "UNKNOWN" in sts else "PASS"
        elif kind == "verdict":
            data_only = {"verdict": p["verdict"], "reasons": p["reasons"], "t": wall(e["ts"]), "stamp": p}
        name = {"step_done": "step", "session_start": "session_start", "evaluation": "evaluation",
                "verdict": "verdict", "session_stopped": "session_stopped"}.get(kind)
        if name:
            stream.append((name, e))
        if kind == "evaluation":
            stream += [("finding", f) for f in findings if f["eval_id"] == e["id"]]
    verdict = data_only["verdict"] if data_only else None
    detail = {"id": folder.name, "plant": plan["plant"], "state": "stopped", "started": wall(start["ts"]),
              "plan_hash": start["payload"]["plan_hash"], "plan": plan, "confirmation": None,
              "assumptions": [a["text"] for a in plan["assumptions"]], "plan_check_override": OVERRIDE,
              "steps": steps, "findings": findings, "verdict": verdict, "verdict_with_camera": verdict,
              "tracks": {"data_only": data_only, "with_camera": None}, "stamp": data_only and data_only["stamp"],
              "refused": [], "camera_pending": 0, "signature": None}
    return detail, stream


def live_session(base: dict, stream: list) -> tuple[dict, list]:
    """A session still in progress: steps 1-2 marked, step 1 verified, one camera read; verdict pending."""
    d = copy.deepcopy(base)
    d.update(id="ui-live", state="ready", verdict=None, verdict_with_camera=None, stamp=None,
             tracks={"data_only": None, "with_camera": None})
    for s in d["steps"]:
        if s["k"] > 2:
            s.update(marked_by=None, marked_t=None, result=None, finding_ids=[])
    d["steps"][0].update(verified_by="eval-verifier", verified_t=d["steps"][0]["marked_t"] + 5)
    keep = {f for s in d["steps"] for f in s["finding_ids"]}
    d["findings"] = [f for f in d["findings"] if f["id"] in keep]
    cam = {"id": "99999:LIVE-CAMERA", "rule_id": "LIVE-CAMERA", "rule_version": "1", "status": "PASS",
           "message": "display reads 0 % open, feedback 0 % open", "refs": ["f1_valve_pos"], "path": [],
           "eval_id": 99999, "source": "camera", "step": 2, "t": d["steps"][1]["marked_t"] + 20}
    d["findings"].append(cam)
    evals = {f["eval_id"] for f in d["findings"]}
    live = [(n, e) for n, e in stream if n == "session_start" or (n == "evaluation" and e["id"] in evals)]
    return d, live


def build_sessions() -> tuple[dict, dict]:
    s0 = min(BENCH.glob("S0_*"))
    out = {}
    for folder in (BENCH / BLOCKED_EP, s0):
        out[folder.name] = episode(folder)
    out["ui-live"] = live_session(*out[s0.name])
    return {k: v[0] for k, v in out.items()}, {k: v[1] for k, v in out.items()}


def frame_jpeg() -> bytes:
    img = Image.new("RGB", (320, 200), (90, 90, 90))
    img.paste((230, 230, 230), (120, 70, 200, 110))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def make_app(data_dir: Path, config_dir: Path, params: dict, ui_dir: Path = ROOT / "ui") -> FastAPI:
    details, streams = build_sessions()
    real = server.create_app(data_dir, data_dir / "audit.sqlite", config_dir, params, opener=FakeOpener(), poll_s=0)
    app = FastAPI()
    real_data = data_dir.resolve() == Path("/data").resolve()

    def write(sid: str, kind: str, body: dict):
        if sid not in details:
            return JSONResponse({"error": "not_found", "detail": sid}, status_code=404)
        if kind == "sign" and body.get("by") == TEST_NAME and real_data:
            return JSONResponse({"error": "test_name_on_real_data", "detail": "refused"}, status_code=403)
        with open(data_dir / "inbox.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"session": sid, "kind": kind, **body}) + "\n")
        return {"queued": True}

    @app.get("/api/sessions")
    def sessions():
        rows = [{"id": d["id"], "plant": d["plant"], "plan_hash": d["plan_hash"], "started": d["started"], "state": d["state"],
                 "verdict": d["verdict"], "verdict_with_camera": d["verdict_with_camera"], "signed": d["signature"] is not None}
                for d in details.values()]
        return sorted(rows, key=lambda r: -r["started"])

    @app.post("/api/sessions")
    async def start(request: Request):
        body = await request.json()
        if not (data_dir / "plans" / f"{body.get('plan_hash')}.json").exists():
            return JSONResponse({"error": "not_found", "detail": "no confirmation for this plan"}, status_code=404)
        write("ui-live", "session_start", body)
        return JSONResponse({"queued": True, "session": "ui-live"}, status_code=202)

    @app.get("/api/sessions/{sid}")
    def detail(sid: str):
        if sid not in details:
            return JSONResponse({"error": "not_found", "detail": sid}, status_code=404)
        return details[sid]

    @app.get("/api/sessions/{sid}/stream")
    def stream(sid: str):
        body = "".join(f"event: {n}\ndata: {json.dumps(e)}\n\n" for n, e in streams.get(sid, []))
        return StreamingResponse(iter([body]), media_type="text/event-stream")

    @app.post("/api/sessions/{sid}/steps/{k}/{action}")
    async def step(sid: str, k: int, action: str, request: Request):
        return write(sid, f"step_{action}", {"k": k, **(await request.json())})

    @app.post("/api/sessions/{sid}/sign")
    async def sign(sid: str, request: Request):
        return write(sid, "sign", await request.json())

    @app.post("/api/sessions/{sid}/explain")
    async def explain(sid: str):
        f = details[sid]["findings"]
        cite = next((x for x in f if x["status"] == "FAIL"), f[0])
        return {"answer": f"The finding {cite['id']} says: {cite['message']}.", "cites": [cite["id"]]}

    @app.get("/api/sessions/{sid}/camera/{eval_id}")
    def camera(sid: str, eval_id: int):
        f = next((x for x in details[sid]["findings"] if x["eval_id"] == eval_id and x["source"] == "camera"), None)
        if f is None:
            return JSONResponse({"error": "not_found", "detail": str(eval_id)}, status_code=404)
        return {"eval_id": eval_id, "step": f["step"], "point": "f1", "tag": "f1_valve_pos", "mode": "advisory",
                "label": "idealised camera (renders the simulator's true state)", "models": ["muse-spark", "sam-3.1"],
                "finding": f, "verdict_after": None, "with_camera_after": None, "feedback": [[f["t"], 0.0]],
                "readings": [{"t": f["t"], "value": 0.0, "readable": True, "note": None, "frame_sha256": "ab" * 32,
                              "box": [120, 70, 200, 110], "crop_hash": "cd" * 32, "feedback_at": 0.0,
                              "frame_url": "/fixture/frame.jpg", "crop_url": None}]}

    jpeg = frame_jpeg()
    app.get("/fixture/frame.jpg")(lambda: Response(jpeg, media_type="image/jpeg"))
    app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")
    app.mount("/", real)
    return app
