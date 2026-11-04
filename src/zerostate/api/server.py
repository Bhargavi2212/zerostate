"""HTTP API for the operator console (docs/API.md). Runs as `zs api` in zs-api, port 8090 on 127.0.0.1 only.

Trust boundaries kept here:
- no plant access: no adapter is imported; zs-api-net lets traffic out to the model proxy only;
- the audit log is opened read-only (SQLite mode=ro): human actions go into the inbox and the core logs them;
- the voice route only reads back; it never touches the inbox, so it can't mark a step, verify, reopen or sign;
- the name `playwright-test` can't confirm or sign while the data dir is the real /data (G10);
- replay mode (`zs api --replay <bundle_dir>`) serves recorded bundles; every write is 409 "replay";
- explain and the check-request resolver (llm/explain.py, llm/resolve.py) only read: they get plain data,
  return text, and touch no inbox, log or session. The data-only verdict path never imports them.
"""

import asyncio
import base64
import hashlib
import io
import itertools
import json
import os
import re
import secrets
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import yaml
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, model_validator
from starlette.exceptions import HTTPException

from zerostate.api.replay import load_bundles
from zerostate.audit.log import AuditLog
from zerostate.importers import draft as dr
from zerostate.importers.confirm import NotConfirmable, confirm, is_confirmed
from zerostate.llm import client as model
from zerostate.llm.client import ModelUnavailable
from zerostate.llm.explain import explain as explain_answer
from zerostate.llm.resolve import resolve
from zerostate.models.envelope import IsolationList, IsolationPlan
from zerostate.models.plant_map import PlantMap
from zerostate.session import Inbox, status_from_events

NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")  # plant and session ids: never a path
SHA = re.compile(r"[0-9a-f]{64}")
SIGN_ROLES = Literal["planner", "approver", "installer", "verifier", "prover", "receiver"]  # as `zs sign`
STREAM_KINDS = {"session_start": "session_start", "step_done": "step", "step_refused": "step", "step_verify": "step_verify",
                "step_reopen": "step_reopen", "evaluation": "evaluation", "camera_reading": "camera_reading",
                "verdict": "verdict", "signature": "signature", "session_stopped": "session_stopped",
                "session_refused": "session_refused"}
END_KINDS = ("signature", "session_stopped", "session_refused")
SUMMARY_KINDS = ("session_start", "session_refused", "ready", "verdict", "signature", "session_stopped")
NDF = "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"
TEST_NAME = "playwright-test"
REAL_DATA = Path("/data")
CAMERA_LABEL = "idealised camera (renders the simulator's true state)"


class By(BaseModel):
    by: str


class Reopen(By):
    reason: str


class Sign(By):
    role: SIGN_ROLES
    note: str | None = None
    outcome: Literal["accepted", "not_accepted"] = "not_accepted"


class Confirm(By):
    role: Literal["issuer"]


class Start(By):
    plant: str
    plan_hash: str
    plan_check_override: str | None = None


class DraftEdit(BaseModel):
    list: IsolationList


class Question(BaseModel):
    question: str


class CheckRequest(BaseModel):
    text: str | None = None
    audio: str | None = None  # base64 WAV (mono 16-bit PCM, 16 or 24 kHz), transcribed by Muse Voice Transcribe

    @model_validator(mode="after")
    def one_input(self):
        if (self.audio is None) == (self.text is None):
            raise ValueError("send either `text` or `audio`")
        return self


class VoiceIn(BaseModel):
    session: str | None = None
    audio: str | None = None  # base64 recording
    transcript: str | None = None
    asr: str | None = None  # id of the model that made `transcript`

    @model_validator(mode="after")
    def one_input(self):
        if (self.audio is None) == (self.transcript is None):
            raise ValueError("send either `audio` or `transcript` (with `asr`)")
        if self.transcript is not None and not self.asr:
            raise ValueError("`transcript` needs `asr`: the id of the model that made it")
        return self


class VoiceReply(BaseModel):
    transcript: str
    asr: str | None
    intent: Literal["step_done", "confirm", "cancel", "status", "why", "repeat", "unknown"]
    k: int | None
    read_back: str


# ---- voice: words -> intent, read-back only ------------------------------------------------------------
NUMBERS = {w: str(i) for i, w in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                                            "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
                                            "seventeen", "eighteen", "nineteen", "twenty"])}
WORDS = {"confirm": {"yes", "confirm", "confirmed", "correct", "affirmative"},
         "cancel": {"no", "cancel", "negative", "abort"},
         "repeat": {"repeat", "again", "pardon"},
         "status": {"status", "progress"}}
NOT_BY_VOICE = {"sign", "signoff", "signature", "verify", "verified", "reopen", "approve", "override", "accept"}
STATE_WORDS = {"closed": {"closed", "close", "shut"}, "open": {"open", "opened"}}


def _undouble(t: str) -> str:
    """A word the transcriber ran together with itself ("confirmconfirm") is that word once. Exact halves
    only: nothing else is rewritten. Added after voice run 3, unmeasured (eval/results/voice_runs.md)."""
    h = len(t) // 2
    return t[:h] if len(t) % 2 == 0 and h >= 2 and t[:h] == t[h:] else t


def _tokens(text: str) -> list[str]:
    return [NUMBERS.get(t, t) for t in (_undouble(w) for w in re.findall(r"[a-z0-9]+", text.lower()))]


def _norm(target: str) -> str:
    return re.sub(r"[^a-z0-9]", "", target.lower())


def _step_words(s: dict) -> tuple[list[str], str | None]:
    targets = list(s.get("targets") or ([s["target"]] if s.get("target") else []))
    rs = s.get("required_state")
    state = None if rs is None else "closed" if rs <= 5 else "open" if rs >= 95 else None
    return targets, state


def _step_text(s: dict) -> str:
    targets, state = _step_words(s)
    what = " and ".join(targets) or s["kind"].replace("_", " ")
    return f"Step {s['k']}: {what}" + (f" {state}" if state else "") + "."


def voice_keywords(plan: dict | None) -> list[str]:
    """Muse Voice Transcribe `keywords` (terms it might mishear): the fixed command words plus the plan's valve
    names. Biases hearing only; parse_intent still needs exact words, so nothing matches loosely."""
    fixed = {w for ws in WORDS.values() for w in ws} | {"step", "done", "mark", "complete", "why", "blocked"}
    fixed |= {w for ws in STATE_WORDS.values() for w in ws}
    valves = {t for s in (plan or {}).get("steps", []) for t in _step_words(s)[0]}
    return sorted(fixed | valves)


def parse_intent(text: str, plan: dict | None) -> tuple[str, int | None, str]:
    """(intent, k, read_back). A step only from its number, or from a phrase naming ALL its targets and its
    state; anything else is `unknown` with a clarifying question, never a guess at a step."""
    toks = _tokens(text)
    words = set(toks)
    steps = [s for s in (plan or {}).get("steps", []) if s["kind"] != "final"]
    if words & NOT_BY_VOICE:
        return "unknown", None, "Signing, verifying and reopening are done on screen, not by voice."
    if "why" in words:
        return "why", None, ""
    for intent in ("cancel", "confirm", "repeat", "status"):
        if words & WORDS[intent] and len(toks) <= 3:
            return intent, None, {"cancel": "Cancelled. Nothing was marked.", "confirm": "Confirmed."}.get(intent, "")
    if "step" in toks and toks.index("step") + 1 < len(toks) and toks[toks.index("step") + 1].isdigit():
        k = int(toks[toks.index("step") + 1])
        hit = [s for s in steps if s["k"] == k]
        if hit:
            return "step_done", k, f"{_step_text(hit[0])} Say confirm to mark it done, or cancel."
        return "unknown", None, f"There is no step {k} to mark. Which step is done?"
    # a target is heard as itself, run together ("f 1" -> f1), or spoken as a word plus number ("feed one" -> f1)
    joined = set(toks) | {a + b for a, b in itertools.pairwise(toks)} | {
        a[0] + b for a, b in itertools.pairwise(toks) if b.isdigit() and not a.isdigit()}
    said = {st for st, ws in STATE_WORDS.items() if words & ws}
    named = {_norm(t) for s in steps for t in _step_words(s)[0] if _norm(t) in joined}  # every plan valve the phrase names
    hits = []
    for s in steps:
        targets, state = _step_words(s)
        if targets and state and {_norm(t) for t in targets} == named and said == {state}:  # exactly this step's valves
            hits.append(s)
    if len(hits) == 1:
        return "step_done", hits[0]["k"], f"{_step_text(hits[0])} Say confirm to mark it done, or cancel."
    return "unknown", None, "I did not catch which step. Say the step number, or every valve of the step and its state."


async def voice_command(body: VoiceIn, request: Request) -> VoiceReply:
    """Reads back only: the console calls /steps/{k}/done after the person confirms. Nothing here writes
    the inbox or reaches /sign, verify or reopen (tests/test_api_contract.py checks this function's names)."""
    ctx = request.app.state
    if ctx.replay:
        raise Replay()
    d = ctx.detail(body.session) if body.session else None
    transcript, asr = body.transcript, body.asr
    if body.audio is not None:  # Muse Voice Transcribe, biased to the command words and the plan's valve names
        try:
            transcript, asr = model.transcribe(base64.b64decode(body.audio), "voice_command", opener=ctx.opener,
                                               keywords=voice_keywords(d["plan"] if d else None)), model.ASR
        except (ModelUnavailable, ValueError):
            return VoiceReply(transcript="", asr=None, intent="unknown", k=None,
                              read_back="I could not transcribe that here. Type the step instead.")
    intent, k, read_back = parse_intent(transcript, d["plan"] if d else None)
    if intent in ("status", "why") and d is None:
        intent, read_back = "unknown", "Which session? Open a job first."
    elif intent == "status":
        nxt = next((s for s in d["steps"] if s["marked_by"] is None and s["kind"] != "final"), None)
        read_back = (f"Data checks: {_say(d['verdict'])}. With camera: {_say(d['verdict_with_camera'])}. "
                     + (f"Next: {_step_text(nxt)}" if nxt else "Every step is marked."))
    elif intent == "why":
        reasons = ((d["tracks"]["data_only"] or {}).get("reasons") or [])
        read_back = " ".join(reasons) or f"Data checks: {_say(d['verdict'])}. No open reasons are logged."
    return VoiceReply(transcript=transcript, asr=asr, intent=intent, k=k, read_back=read_back)


def _say(verdict: str | None) -> str:
    return {"BLOCKED": "blocked", "ESCALATED": "escalated", NDF: "no discrepancy found, awaiting sign-off"}.get(verdict, "evaluating")


# ---- session views, built from audit-style events (live log or a replayed bundle) -------------------------
def _t(e: dict) -> float | None:
    return e["t"] if e.get("t") is not None else datetime.fromisoformat(e["ts"]).timestamp() if e.get("ts") else None


def finding_id(eval_id, rule_id: str) -> str:
    return f"{eval_id}:{rule_id}"


def summary(sid: str, ev: list[dict]) -> dict:
    s = status_from_events(ev)
    start = next((e for e in ev if e["kind"] == "session_start"), None)
    plan = start["payload"]["plan"] if start else {}
    return {"id": sid, "plant": plan.get("plant") or ev[0]["payload"].get("plant"), "plan_hash": start["payload"].get("plan_hash") if start else None,
            "started": _t(start or ev[0]), "state": s["state"], "verdict": s["verdict"],
            "verdict_with_camera": s["verdict_with_camera"], "signed": "signature" in s}


def detail(sid: str, ev: list[dict]) -> dict:
    s = status_from_events(ev)
    start = next((e for e in ev if e["kind"] == "session_start"), None)
    sp = start["payload"] if start else {}
    plan = sp.get("plan")
    steps = {st["k"]: {"k": st["k"], "kind": st["kind"],
                       "targets": list(st.get("targets") or ([st["target"]] if st.get("target") else [])),
                       "required_state": st.get("required_state"), "marked_by": None, "marked_t": None,
                       "verified_by": None, "verified_t": None, "reopened": [], "result": None, "finding_ids": []}
             for st in (plan or {}).get("steps", [])}
    findings, data_v, cam_v = [], None, None
    for e in ev:
        p, kind, t = e["payload"], e["kind"], _t(e)
        st = steps.get(p.get("k"))
        if kind == "step_done" and st and not p.get("out_of_order"):
            st.update(marked_by=p.get("by"), marked_t=t)
        elif kind == "step_verify" and st:
            st.update(verified_by=p.get("by"), verified_t=t)
        elif kind == "step_reopen" and st:
            st["reopened"].append({"by": p.get("by"), "t": t, "reason": p.get("reason")})
            for j in p.get("pending", []):
                if j in steps:
                    steps[j].update(marked_by=None, marked_t=None, verified_by=None, verified_t=None)
        elif kind == "evaluation":
            for f in p.get("findings", []):
                fid = finding_id(e["id"], f["rule_id"])
                findings.append({**f, "id": fid, "eval_id": e["id"], "source": p.get("source"), "step": p.get("step"), "t": t})
                if p.get("step") in steps:
                    steps[p["step"]]["finding_ids"].append(fid)
        elif kind == "verdict" and p.get("track") == "with_camera":
            cam_v = {"verdict": p["verdict"], "reasons": p.get("reasons", []), "t": t, "stamp": p, "models": p.get("models")}
        elif kind == "verdict":
            data_v = {"verdict": p["verdict"], "reasons": p.get("reasons", []), "t": t, "stamp": p}
    for k, v in s["steps"].items():
        if int(k) in steps:
            steps[int(k)]["result"] = None if v == "pending" else v
    with_cam = None
    if s["verdict_with_camera"] is not None:
        reasons = list(dict.fromkeys((data_v or {}).get("reasons", []) + (cam_v or {}).get("reasons", [])))
        with_cam = {"verdict": s["verdict_with_camera"], "reasons": reasons, "t": max(x["t"] for x in (data_v, cam_v) if x),
                    "stamp": (cam_v or data_v)["stamp"], "models": (cam_v or {}).get("models")}
    sig = next((e for e in ev if e["kind"] == "signature"), None)
    return {
        "id": sid, "plant": (plan or {}).get("plant") or ev[0]["payload"].get("plant"),
        "state": s["state"], "started": _t(start or ev[0]),
        "plan_hash": sp.get("plan_hash"), "plan": plan, "confirmation": sp.get("confirmation"),
        "assumptions": [a["text"] for a in (plan or {}).get("assumptions", [])],
        "plan_check_override": sp.get("plan_check_override"),
        "steps": [steps[k] for k in sorted(steps)], "findings": findings,
        "verdict": s["verdict"], "verdict_with_camera": s["verdict_with_camera"],
        "tracks": {"data_only": data_v, "with_camera": with_cam},
        "stamp": s["stamp"], "refused": s["refused"],
        "camera_pending": s["camera_pending"],
        "signature": {"outcome": "not_accepted", **sig["payload"], "t": _t(sig)} if sig else None,
    }


# ---- the app -------------------------------------------------------------------------------------------
def _err(status: int, error: str, detail) -> JSONResponse:
    return JSONResponse({"error": error, "detail": str(detail)}, status_code=status)


def _name(value: str, what: str) -> str:
    if not NAME.fullmatch(value):
        raise HTTPException(400, f"bad {what} id")
    return value


class Replay(Exception):
    pass


class TestName(Exception):
    pass


def create_app(data_dir: str | Path, audit_path: str | Path, config_dir: str | Path, params: dict,
               opener=None, poll_s: float = 1.0, replay_dir: str | Path | None = None,
               ui_dir: str | Path | None = None) -> FastAPI:
    """params: thresholds for the plan checks; opener: model transport (tests pass a fake);
    replay_dir: serve the bundles under it read-only instead of the audit log;
    ui_dir: the console's static files, served at /ui/ (default ZS_UI, else ui/ in this repo)."""
    data, audit, config = Path(data_dir), Path(audit_path), Path(config_dir)
    recorded = load_bundles(replay_dir) if replay_dir is not None else None
    bundles = {sid: r["bundle"] for sid, r in recorded.items()} if recorded is not None else None
    replay_events = {sid: r["events"] for sid, r in (recorded or {}).items()}
    app = FastAPI(title="ZeroState API")

    app.add_exception_handler(HTTPException, lambda r, e: _err(e.status_code, {400: "bad_input", 404: "not_found", 409: "conflict"}.get(e.status_code, "error"), e.detail))
    app.add_exception_handler(RequestValidationError, lambda r, e: _err(400, "bad_input", e.errors()))
    app.add_exception_handler(NotConfirmable, lambda r, e: _err(409, "not_confirmable", e))
    app.add_exception_handler(FileNotFoundError, lambda r, e: _err(404, "not_found", e))
    app.add_exception_handler(ValueError, lambda r, e: _err(400, "bad_input", e))
    app.add_exception_handler(ModelUnavailable, lambda r, e: _err(503, "model_unavailable", e))
    app.add_exception_handler(Replay, lambda r, e: _err(409, "replay", "replay mode serves recorded sessions read-only"))
    app.add_exception_handler(TestName, lambda r, e: _err(403, "test_name_on_real_data",
                                                          f"`{TEST_NAME}` may confirm or sign only with a throwaway data dir"))

    def writable(by: str | None = None) -> None:
        if bundles is not None:
            raise Replay()
        if by is not None and by.strip() == TEST_NAME and data.resolve() == REAL_DATA.resolve():
            raise TestName()

    def plant_map(plant: str) -> PlantMap:
        _name(plant, "plant")
        for b in (bundles or {}).values():
            if b.get("plant") == plant and b.get("plant_map"):
                return PlantMap.model_validate(b["plant_map"])
        p = config / plant / "plant_map.yaml"
        if not p.exists():
            raise HTTPException(404, f"no plant {plant}")
        return PlantMap.model_validate(yaml.safe_load(p.read_text(encoding="utf-8-sig")))

    def draft_view(d: dict) -> dict:
        _, v = dr.check_draft(d, plant_map(d["list"]["plant"]), params)
        return {"id": d["id"], "route": d["route"], "plant": d["list"]["plant"], "list": d["list"],
                "transcript": d.get("transcript"), "plan_hash": v["plan_hash"], "findings": v["findings"],
                "unresolved": v["unresolved"], "defaults": v["defaults"]}

    def read_log(fn):
        try:
            log = AuditLog(audit, read_only=True)
        except sqlite3.OperationalError:
            return None
        try:
            return fn(log)
        finally:
            log.close()

    def events(sid: str) -> list[dict]:
        _name(sid, "session")
        ev = replay_events.get(sid) if bundles is not None else read_log(lambda log: log.events(sid))
        if not ev:
            raise HTTPException(404, f"no session {sid}")
        return ev

    def summaries() -> list[dict]:
        if bundles is not None:
            groups = replay_events
        else:
            def q(log):
                rows = log.db.execute(f"SELECT id, ts, session, kind, payload_json FROM events WHERE kind IN "
                                      f"({','.join('?' * len(SUMMARY_KINDS))}) ORDER BY id", SUMMARY_KINDS).fetchall()
                g: dict[str, list] = {}
                for rid, ts, sid, kind, pj in rows:
                    g.setdefault(sid, []).append({"id": rid, "ts": ts, "session": sid, "kind": kind, "payload": json.loads(pj)})
                return g
            groups = read_log(q) or {}
        out = [summary(sid, ev) for sid, ev in groups.items()]
        return sorted(out, key=lambda s: s["started"] or 0, reverse=True)

    def queue(sid: str, kind: str, **payload) -> dict:
        events(sid)  # 404 for an unknown session
        inbox = Inbox(data / "inbox.sqlite")
        try:
            inbox.put(sid, kind, **payload)
        finally:
            inbox.db.close()
        return {"queued": True}

    def confirmed_plans() -> list[dict]:
        """Every plan a person confirmed: plan files in the plant config with a confirmed.yaml record, and
        confirmed importer drafts (<data>/plans/<hash>.json); in replay mode, the recorded sessions' plans."""
        found: dict[str, tuple[dict, dict]] = {}
        if bundles is not None:
            for b in bundles.values():
                if b.get("plan") and b.get("plan_hash") and b.get("confirmation"):
                    found.setdefault(b["plan_hash"], (b["plan"], b["confirmation"]))
        else:
            for d in sorted(x for x in config.glob("*") if (x / "confirmed.yaml").exists()):
                for y in sorted(d.glob("*.yaml")):
                    try:
                        plan = IsolationPlan.model_validate(yaml.safe_load(y.read_text(encoding="utf-8-sig")))
                    except Exception:  # noqa: BLE001 - not a plan file (map, thresholds, confirmations)
                        plan = None
                    rec = plan and is_confirmed(plan.content_hash(), [d], data)
                    if rec:
                        found.setdefault(plan.content_hash(), (plan.model_dump(mode="json"), rec))
            for f in sorted((data / "plans").glob("*.json")) if (data / "plans").is_dir() else []:
                rec = is_confirmed(f.stem, [], data)
                if rec:
                    found.setdefault(f.stem, (json.loads(f.read_text(encoding="utf-8"))["plan"], rec))
        return [{"id": f"plan-{h[:8]}", "plant": plan.get("plant"), "equipment": (plan.get("work") or {}).get("equipment"),
                 "task": (plan.get("work") or {}).get("task"), "plan_hash": h, "confirmed_by": rec.get("by"),
                 "confirmed_date": rec.get("date")} for h, (plan, rec) in found.items()]

    app.state.replay = bundles is not None
    app.state.opener = opener
    app.state.detail = lambda sid: detail(sid, events(sid))

    @app.get("/api/plants/{plant}/map")
    def get_map(plant: str):
        return plant_map(plant).model_dump(mode="json")

    @app.post("/api/plans/import")
    def import_plan(route: Annotated[Literal["csv", "text", "image"], Form()], plant: Annotated[str, Form()],
                    file: Annotated[UploadFile | None, File()] = None, text: Annotated[str | None, Form()] = None):
        from zerostate.importers.csv_import import parse_csv
        from zerostate.importers.image_import import import_image
        from zerostate.importers.text_import import import_text

        writable()
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
        writable()
        d = dr.load_draft(draft_id, data)
        if body.list.plant != d["list"]["plant"]:
            raise HTTPException(400, f"draft {draft_id} is for plant {d['list']['plant']}")
        d["list"] = body.list.model_dump(mode="json")
        dr.put(data / "drafts" / f"{draft_id}.json", json.dumps(d, indent=2))
        return draft_view(d)

    @app.post("/api/plans/drafts/{draft_id}/confirm")
    def confirm_draft(draft_id: str, body: Confirm):
        writable(body.by)
        if not body.by.strip():
            raise HTTPException(400, "a confirmation needs a person's name")
        rec = confirm(draft_id, body.by, body.role, data_dir=data, config_dir=config, params=params)
        return {k: rec[k] for k in ("plan_hash", "by", "role", "date")}

    @app.get("/api/sessions")
    def list_sessions():
        return summaries()

    @app.post("/api/sessions", status_code=202)
    def start_session(body: Start):
        writable()
        _name(body.plant, "plant")
        if not SHA.fullmatch(body.plan_hash):
            raise HTTPException(400, "plan_hash is a 64-character sha256")
        if not body.by.strip():
            raise HTTPException(400, "a session start needs a person's name")
        if is_confirmed(body.plan_hash, [config / body.plant], data) is None:
            raise HTTPException(404, f"plan {body.plan_hash} has no confirmation by a person")
        sid = f"{body.plant}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{secrets.token_hex(2)}"
        inbox = Inbox(data / "inbox.sqlite")
        try:
            inbox.put(sid, "session_start", plant=body.plant, plan_hash=body.plan_hash, by=body.by,
                      plan_check_override=body.plan_check_override)
        finally:
            inbox.db.close()
        return {"queued": True, "session": sid}

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str):
        return detail(sid, events(sid))

    @app.get("/api/sessions/{sid}/stream")
    async def stream(sid: str, request: Request, speed: float | None = None):
        events(sid)
        signals = data / "runs" / sid / "signals.jsonl"

        def sse(e: dict) -> str:
            out = f"id: {e['id']}\n" if e.get("id") is not None else ""
            out += f"event: {STREAM_KINDS[e['kind']]}\ndata: {json.dumps(e)}\n\n"
            for f in e["payload"].get("findings", []) if e["kind"] == "evaluation" else []:
                out += f"event: finding\ndata: {json.dumps({**f, 'id': finding_id(e['id'], f['rule_id']), 'eval_id': e['id']})}\n\n"
            return out

        async def replayed():
            ev, prev = events(sid), None
            for e in ev:
                if speed and prev is not None and e["t"] is not None:
                    await asyncio.sleep(max(0.0, (e["t"] - prev) / speed))
                prev = e["t"] if e["t"] is not None else prev
                if e["kind"] in STREAM_KINDS:
                    yield sse(e)
                if await request.is_disconnected():
                    return

        def poll(last_id: int, offset: int) -> tuple[list[dict], bytes | None, int]:
            new = [e for e in events(sid) if e["id"] > last_id]
            if not signals.exists():
                return new, None, offset
            with open(signals, "rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
            whole = chunk[:chunk.rfind(b"\n") + 1]  # complete lines only; a half-written one waits
            return new, (whole.splitlines() or [None])[-1], offset + len(whole)

        async def live():
            last_id, offset = 0, 0
            while True:
                new, latest, offset = await asyncio.to_thread(poll, last_id, offset)
                for e in new:
                    last_id = e["id"]
                    if e["kind"] in STREAM_KINDS:
                        yield sse(e)
                if latest:  # the newest sample only, once per poll: <= 1 Hz
                    yield f"event: signals\ndata: {latest.decode().strip()}\n\n"
                if any(e["kind"] in END_KINDS for e in new) or await request.is_disconnected():
                    return
                await asyncio.sleep(poll_s)

        return StreamingResponse(replayed() if bundles is not None else live(), media_type="text/event-stream")

    def camera_eval(sid: str, eval_id: int) -> tuple[dict, list[dict]]:
        ev = events(sid)
        e = next((x for x in ev if x["kind"] == "evaluation" and x["id"] == eval_id
                  and x["payload"].get("source") == "camera"), None)
        if e is None:
            raise HTTPException(404, f"no camera evaluation {eval_id} in {sid}")
        p = e["payload"]
        readings = p.get("readings")
        if readings is None:  # a bundle keeps readings in `camera`: one burst per step and point
            readings = [c for c in (x["payload"] for x in ev if x["kind"] == "camera_reading")
                        if c.get("step") == p.get("step") and c.get("point") == p.get("point")]
        return e, readings

    def frame_path(sid: str, sha: str | None) -> Path | None:
        if bundles is not None or not sha or not SHA.fullmatch(sha):
            return None
        p = data / "frames" / sid / f"{sha}.jpg"
        return p if p.exists() else None

    @app.get("/api/sessions/{sid}/camera/{eval_id}")
    def get_camera(sid: str, eval_id: int):
        e, readings = camera_eval(sid, eval_id)
        p, base = e["payload"], f"/api/sessions/{sid}"
        f = (p.get("findings") or [None])[0]
        out = []
        for i, r in enumerate(readings):
            kept = frame_path(sid, r.get("frame_sha256")) is not None
            out.append({**{k: r.get(k) for k in ("t", "value", "readable", "note", "frame_sha256", "box", "crop_hash", "feedback_at")},
                        "frame_url": f"{base}/frames/{r['frame_sha256']}.jpg" if kept else None,
                        "crop_url": f"{base}/camera/{eval_id}/crop/{i}.png" if kept and r.get("box") else None})
        return {"eval_id": eval_id, "step": p.get("step"), "point": p.get("point"), "tag": p.get("tag"),
                "mode": p.get("camera"), "label": CAMERA_LABEL, "models": p.get("models"),
                "finding": {**f, "id": finding_id(eval_id, f["rule_id"])} if f else None,
                "verdict_after": p.get("verdict_after"), "with_camera_after": p.get("with_camera_after"),
                "feedback": p.get("feedback") or [], "readings": out}

    @app.get("/api/sessions/{sid}/frames/{name}")
    def get_frame(sid: str, name: str):
        events(sid)
        p = frame_path(sid, name.removesuffix(".jpg")) if name.endswith(".jpg") else None
        if p is None:
            raise HTTPException(404, "frame not kept")
        return Response(p.read_bytes(), media_type="image/jpeg")

    @app.get("/api/sessions/{sid}/camera/{eval_id}/crop/{name}")
    def get_crop(sid: str, eval_id: int, name: str):
        from PIL import Image

        from zerostate.camera.read import crop

        _, readings = camera_eval(sid, eval_id)
        i = int(name.removesuffix(".png")) if re.fullmatch(r"\d{1,3}\.png", name) else -1
        r = readings[i] if 0 <= i < len(readings) else {}
        p = frame_path(sid, r.get("frame_sha256"))
        if p is None or not r.get("box"):
            raise HTTPException(404, "crop not available: frame not kept or display not located")
        data_ = p.read_bytes()
        if hashlib.sha256(data_).hexdigest() != r["frame_sha256"]:
            raise HTTPException(409, "saved frame does not match its logged hash")
        buf = io.BytesIO()
        crop(Image.open(io.BytesIO(data_)), r["box"]).convert("RGB").save(buf, "PNG")
        return Response(buf.getvalue(), media_type="image/png")

    @app.post("/api/sessions/{sid}/steps/{k}/done")
    def step_done(sid: str, k: int, body: By):
        writable()
        return queue(sid, "step_done", k=k, by=body.by)

    @app.post("/api/sessions/{sid}/steps/{k}/verify")
    def step_verify(sid: str, k: int, body: By):
        writable()
        return queue(sid, "step_verify", k=k, by=body.by)

    @app.post("/api/sessions/{sid}/steps/{k}/reopen")
    def step_reopen(sid: str, k: int, body: Reopen):
        writable()
        return queue(sid, "step_reopen", k=k, by=body.by, reason=body.reason)

    @app.post("/api/sessions/{sid}/sign")
    def sign(sid: str, body: Sign):
        writable(body.by)
        if body.outcome == "accepted":
            s = status_from_events(events(sid))
            if s["verdict"] != NDF or s["verdict_with_camera"] != NDF:
                raise HTTPException(409, "`accepted` needs both tracks at NO DISCREPANCY FOUND; use `not_accepted` to close")
            if s["camera_pending"] > 0:
                raise HTTPException(409, f"camera still checking: {s['camera_pending']} reads pending; sign when they are in")
        return queue(sid, "sign", by=body.by, role=body.role, note=body.note, outcome=body.outcome)

    @app.post("/api/sessions/{sid}/explain")
    def explain(sid: str, body: Question):
        """Read only: the answer is built from the session's logged findings and returned; nothing is written."""
        return explain_answer(body.question, detail(sid, events(sid)), opener=opener)

    @app.get("/api/checks/plans")
    def check_plans():
        return confirmed_plans()

    @app.post("/api/checks/resolve")
    def check_resolve(body: CheckRequest):
        """Read only: a request -> one confirmed plan or none. Starts no session, confirms and signs nothing."""
        plans, asr = confirmed_plans(), None
        text = body.text
        if body.audio is not None:
            try:
                wav = base64.b64decode(body.audio, validate=True)
            except ValueError:
                raise HTTPException(400, "audio is not base64") from None
            text, asr = model.transcribe(wav, "check_request", opener=opener,
                                         keywords=sorted({w for p in plans for w in (p["equipment"], p["plant"]) if w})), model.ASR
        r = resolve(text or "", plans, opener=opener)
        pick = next((p for p in plans if p["id"] == r["plan_id"]), None)
        return {"text": text, "asr": asr, "plans": plans, "plan": pick, "reason": r["reason"]}

    app.post("/api/voice/command", response_model=VoiceReply)(voice_command)

    ui = Path(ui_dir or os.environ.get("ZS_UI") or Path(__file__).parents[3] / "ui")
    if ui.is_dir():  # the console: relative assets, calls to absolute /api/...
        app.get("/", include_in_schema=False)(lambda: RedirectResponse("/ui/"))
        app.mount("/ui", StaticFiles(directory=ui, html=True), name="ui")
    return app
