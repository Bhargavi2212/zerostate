"""Fixture server for the console's Playwright tests (P3-3).

- Plans, drafts and confirm: the real `zerostate.api.server` app on a throwaway data dir, with a fake
  model transport (never the Meta API).
- Recorded sessions: replay mode (`zs api --replay`) over the committed sample bundles
  (eval/results/bench/p1/*/bundle.json.gz, G9); their GETs go to the replay app unchanged.
- One in-progress session (`ui-live`), faked from the S0 recording: the one thing a bundle can't give.
- Writes (done / verify / sign / session start) only append to <data>/inbox.jsonl in the throwaway dir
  (replay mode itself refuses them). Like the API, a sign by `playwright-test` is refused (403) when the
  data dir is the real /data.
"""

import copy
import io
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from PIL import Image

from zerostate.api import server
from zerostate.api.replay import load_bundles

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


def sse(e: dict) -> str:
    out = f"event: {server.STREAM_KINDS[e['kind']]}\ndata: {json.dumps(e)}\n\n"
    for f in e["payload"].get("findings", []) if e["kind"] == "evaluation" else []:
        out += f"event: finding\ndata: {json.dumps({**f, 'id': server.finding_id(e['id'], f['rule_id']), 'eval_id': e['id']})}\n\n"
    return out


def live_session(base: dict, events: list) -> tuple[dict, str]:
    """A session still in progress: steps 1-2 marked, step 1 verified, one camera read; verdict pending."""
    d = copy.deepcopy(base)
    d.update(id="ui-live", state="ready", verdict=None, verdict_with_camera=None, stamp=None, plan_check_override=OVERRIDE,
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
    live = [e for e in events if e["kind"] == "session_start" or (e["kind"] == "evaluation" and e["id"] in evals)]
    return d, "".join(sse(e) for e in live)


def frame_jpeg() -> bytes:
    img = Image.new("RGB", (320, 200), (90, 90, 90))
    img.paste((230, 230, 230), (120, 70, 200, 110))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def make_app(data_dir: Path, config_dir: Path, params: dict, ui_dir: Path = ROOT / "ui") -> FastAPI:
    events = {sid: r["events"] for sid, r in load_bundles(BENCH).items()}
    details = {sid: server.detail(sid, ev) for sid, ev in events.items()}
    s0 = min(k for k in details if k.startswith("S0_"))
    live, live_stream = live_session(details[s0], events[s0])
    details["ui-live"] = live
    real = server.create_app(data_dir, data_dir / "audit.sqlite", config_dir, params, opener=FakeOpener(), poll_s=0, ui_dir=ui_dir)
    replay = server.create_app(BENCH, BENCH / "no-audit.sqlite", config_dir, {}, replay_dir=BENCH, ui_dir=ui_dir)
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
        rows = [server.summary(sid, ev) for sid, ev in events.items()]
        rows.append({"id": "ui-live", "plant": live["plant"], "plan_hash": live["plan_hash"], "started": live["started"],
                     "state": live["state"], "verdict": None, "verdict_with_camera": None, "signed": False})
        return sorted(rows, key=lambda r: -r["started"])

    @app.post("/api/sessions")
    async def start(request: Request):
        body = await request.json()
        if not (data_dir / "plans" / f"{body.get('plan_hash')}.json").exists():
            return JSONResponse({"error": "not_found", "detail": "no confirmation for this plan"}, status_code=404)
        write("ui-live", "session_start", body)
        return JSONResponse({"queued": True, "session": "ui-live"}, status_code=202)

    @app.get("/api/sessions/ui-live")
    def live_detail():
        return live

    # both tracks at NO DISCREPANCY while 2 camera reads are still pending (seen in the Nov 3 smoke S0 runs)
    pending = {**copy.deepcopy(details[s0]), "id": "ui-camera-pending", "camera_pending": 2}

    @app.get("/api/sessions/ui-camera-pending")
    def pending_detail():
        return pending

    @app.get("/api/sessions/ui-camera-pending/stream")
    def pending_events():
        return StreamingResponse(iter([]), media_type="text/event-stream")

    @app.get("/api/sessions/ui-live/stream")
    def live_events():
        return StreamingResponse(iter([live_stream]), media_type="text/event-stream")

    @app.get("/api/sessions/ui-live/camera/{eval_id}")
    def camera(eval_id: int):
        f = next((x for x in live["findings"] if x["eval_id"] == eval_id and x["source"] == "camera"), None)
        if f is None:
            return JSONResponse({"error": "not_found", "detail": str(eval_id)}, status_code=404)
        return {"eval_id": eval_id, "step": f["step"], "point": "f1", "tag": "f1_valve_pos", "mode": "advisory",
                "label": "idealised camera (renders the simulator's true state)", "models": ["muse-spark", "sam-3.1"],
                "finding": f, "verdict_after": None, "with_camera_after": None, "feedback": [[f["t"], 0.0]],
                "readings": [{"t": f["t"], "value": 0.0, "readable": True, "note": None, "frame_sha256": "ab" * 32,
                              "box": [120, 70, 200, 110], "crop_hash": "cd" * 32, "feedback_at": 0.0,
                              "frame_url": "/fixture/frame.jpg", "crop_url": None}]}

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

    jpeg = frame_jpeg()
    app.get("/fixture/frame.jpg")(lambda: Response(jpeg, media_type="image/jpeg"))

    async def split(scope, receive, send):
        """Recorded sessions' GETs go to replay mode; everything else (plans, drafts, confirm, /ui/) to the live app."""
        to_replay = scope["type"] == "http" and scope["method"] == "GET" and scope["path"].startswith("/api/sessions/")
        await (replay if to_replay else real)(scope, receive, send)

    app.mount("/", split)
    return app
