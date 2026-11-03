"""HTTP API for the operator console (docs/API.md). Runs as `zs api` in zs-api, port 8090 on 127.0.0.1 only.

Trust boundaries kept here:
- no plant access: no adapter is imported; zs-api-net lets traffic out to the model proxy only;
- the audit log is opened read-only (SQLite mode=ro): human actions go into the inbox and the core logs them;
- the voice route only reads back; it never touches the inbox, so it can't mark a step or sign.
Explain and voice are stubs until Phase 3.
"""

import asyncio
import json
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Annotated, Literal

import yaml
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from zerostate.audit.log import AuditLog
from zerostate.importers import draft as dr
from zerostate.importers.confirm import NotConfirmable, confirm
from zerostate.llm.client import ModelUnavailable
from zerostate.models.envelope import IsolationList
from zerostate.models.plant_map import PlantMap
from zerostate.session import Inbox, status_from_events

NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")  # plant and session ids: never a path
SIGN_ROLES = Literal["planner", "approver", "installer", "verifier", "prover", "receiver"]  # as `zs sign`
STREAM_KINDS = {"evaluation": "evaluation", "verdict": "verdict", "step_done": "step", "step_refused": "step"}
END_KINDS = ("signature", "session_stopped")


class By(BaseModel):
    by: str


class Reopen(By):
    reason: str


class Sign(By):
    role: SIGN_ROLES
    note: str | None = None


class Confirm(By):
    role: Literal["issuer"]


class DraftEdit(BaseModel):
    list: IsolationList


class Question(BaseModel):
    question: str


class Audio(BaseModel):
    audio: str  # base64 recording (Phase 3)


class VoiceReply(BaseModel):
    transcript: str
    intent: Literal["step_done", "status", "why", "repeat", "unknown"]
    k: int | None
    read_back: str


def voice_command(body: Audio) -> VoiceReply:
    """Phase 2 stub. Reads back only: the console calls /steps/{k}/done after the person confirms, and
    nothing here can reach /sign (tests/test_api_contract.py checks this function's names)."""
    return VoiceReply(transcript="", intent="unknown", k=None, read_back="Voice commands arrive in Phase 3.")


def _err(status: int, error: str, detail) -> JSONResponse:
    return JSONResponse({"error": error, "detail": str(detail)}, status_code=status)


def _name(value: str, what: str) -> str:
    if not NAME.fullmatch(value):
        raise HTTPException(400, f"bad {what} id")
    return value


def create_app(data_dir: str | Path, audit_path: str | Path, config_dir: str | Path, params: dict,
               opener=None, poll_s: float = 1.0) -> FastAPI:
    """params: thresholds for the plan checks; opener: model transport (tests pass a fake)."""
    data, audit, config = Path(data_dir), Path(audit_path), Path(config_dir)
    app = FastAPI(title="ZeroState API")

    app.add_exception_handler(HTTPException, lambda r, e: _err(e.status_code, {400: "bad_input", 404: "not_found", 409: "conflict"}.get(e.status_code, "error"), e.detail))
    app.add_exception_handler(RequestValidationError, lambda r, e: _err(400, "bad_input", e.errors()))
    app.add_exception_handler(NotConfirmable, lambda r, e: _err(409, "not_confirmable", e))
    app.add_exception_handler(FileNotFoundError, lambda r, e: _err(404, "not_found", e))
    app.add_exception_handler(ValueError, lambda r, e: _err(400, "bad_input", e))
    app.add_exception_handler(ModelUnavailable, lambda r, e: _err(503, "model_unavailable", e))

    def plant_map(plant: str) -> PlantMap:
        p = config / _name(plant, "plant") / "plant_map.yaml"
        if not p.exists():
            raise HTTPException(404, f"no plant {plant}")
        return PlantMap.model_validate(yaml.safe_load(p.read_text(encoding="utf-8-sig")))

    def draft_view(d: dict) -> dict:
        _, v = dr.check_draft(d, plant_map(d["list"]["plant"]), params)
        return {"id": d["id"], "route": d["route"], "plant": d["list"]["plant"], "list": d["list"],
                "transcript": d.get("transcript"), "plan_hash": v["plan_hash"], "findings": v["findings"],
                "unresolved": v["unresolved"], "defaults": v["defaults"]}

    def events(sid: str) -> list[dict]:
        try:
            log = AuditLog(audit, read_only=True)
        except sqlite3.OperationalError:
            raise HTTPException(404, f"no session {sid}") from None
        try:
            ev = log.events(_name(sid, "session"))
        finally:
            log.close()
        if not ev:
            raise HTTPException(404, f"no session {sid}")
        return ev

    def queue(sid: str, kind: str, **payload) -> dict:
        events(sid)  # 404 for an unknown session
        inbox = Inbox(data / "inbox.sqlite")
        try:
            inbox.put(sid, kind, **payload)
        finally:
            inbox.db.close()
        return {"queued": True}

    @app.get("/api/plants/{plant}/map")
    def get_map(plant: str):
        return plant_map(plant).model_dump(mode="json")

    @app.post("/api/plans/import")
    def import_plan(route: Annotated[Literal["csv", "text", "image"], Form()], plant: Annotated[str, Form()],
                    file: Annotated[UploadFile | None, File()] = None, text: Annotated[str | None, Form()] = None):
        from zerostate.importers.csv_import import parse_csv
        from zerostate.importers.image_import import import_image
        from zerostate.importers.text_import import import_text

        pmap, transcript = plant_map(plant), None
        if route == "text" and text is None and file is not None:
            text = file.file.read().decode("utf-8-sig")
        if route == "text":
            if not text:
                raise HTTPException(400, "the text route needs `text`")
            lst, source = import_text(text, pmap, opener=opener), "typed text"
        else:
            if file is None or not file.filename:
                raise HTTPException(400, f"the {route} route needs `file`")
            source = Path(file.filename).name
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / ("upload" + Path(source).suffix.lower())
                with open(p, "wb") as fh:
                    fh.write(file.file.read())
                if route == "csv":
                    lst = parse_csv(p, plant)
                else:
                    lst, transcript = import_image(p, pmap, opener=opener)
        return draft_view(dr.save_draft(lst, route, source, data, transcript))

    @app.get("/api/plans/drafts/{draft_id}")
    def get_draft(draft_id: str):
        return draft_view(dr.load_draft(draft_id, data))

    @app.put("/api/plans/drafts/{draft_id}")
    def put_draft(draft_id: str, body: DraftEdit):
        d = dr.load_draft(draft_id, data)
        if body.list.plant != d["list"]["plant"]:
            raise HTTPException(400, f"draft {draft_id} is for plant {d['list']['plant']}")
        d["list"] = body.list.model_dump(mode="json")
        dr.put(data / "drafts" / f"{draft_id}.json", json.dumps(d, indent=2))
        return draft_view(d)

    @app.post("/api/plans/drafts/{draft_id}/confirm")
    def confirm_draft(draft_id: str, body: Confirm):
        if not body.by.strip():
            raise HTTPException(400, "a confirmation needs a person's name")
        rec = confirm(draft_id, body.by, body.role, data_dir=data, config_dir=config, params=params)
        return {k: rec[k] for k in ("plan_hash", "by", "role", "date")}

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str):
        s = status_from_events(events(sid))
        s.setdefault("verdict_with_camera", None)  # camera track (P2-4) adds these to `zs status`
        s.setdefault("camera_pending", 0)
        return s

    @app.get("/api/sessions/{sid}/stream")
    async def stream(sid: str, request: Request):
        events(sid)
        signals = data / "runs" / sid / "signals.jsonl"

        def poll(last_id: int, offset: int) -> tuple[list[dict], bytes | None, int]:
            new = [e for e in events(sid) if e["id"] > last_id]
            if not signals.exists():
                return new, None, offset
            with open(signals, "rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
            whole = chunk[:chunk.rfind(b"\n") + 1]  # complete lines only; a half-written one waits
            return new, (whole.splitlines() or [None])[-1], offset + len(whole)

        async def gen():
            last_id, offset = 0, 0
            while True:
                new, latest, offset = await asyncio.to_thread(poll, last_id, offset)
                for e in new:
                    last_id = e["id"]
                    if e["kind"] in STREAM_KINDS:
                        yield f"id: {e['id']}\nevent: {STREAM_KINDS[e['kind']]}\ndata: {json.dumps(e)}\n\n"
                    for f in e["payload"].get("findings", []) if e["kind"] == "evaluation" else []:
                        yield f"event: finding\ndata: {json.dumps(f)}\n\n"
                if latest:  # the newest sample only, once per poll: <= 1 Hz
                    yield f"event: signals\ndata: {latest.decode().strip()}\n\n"
                if any(e["kind"] in END_KINDS for e in new) or await request.is_disconnected():
                    return
                await asyncio.sleep(poll_s)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/sessions/{sid}/steps/{k}/done")
    def step_done(sid: str, k: int, body: By):
        return queue(sid, "step_done", k=k, by=body.by)

    @app.post("/api/sessions/{sid}/steps/{k}/verify")
    def step_verify(sid: str, k: int, body: By):
        return queue(sid, "step_verify", k=k, by=body.by)

    @app.post("/api/sessions/{sid}/steps/{k}/reopen")
    def step_reopen(sid: str, k: int, body: Reopen):
        return queue(sid, "step_reopen", k=k, by=body.by, reason=body.reason)

    @app.post("/api/sessions/{sid}/sign")
    def sign(sid: str, body: Sign):
        return queue(sid, "sign", by=body.by, role=body.role, note=body.note)

    @app.post("/api/sessions/{sid}/explain")
    def explain(sid: str, body: Question):
        events(sid)
        return {"answer": "Explanations arrive in Phase 3; see the logged findings.", "cites": []}

    app.post("/api/voice/command", response_model=VoiceReply)(voice_command)
    return app
