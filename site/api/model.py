"""The site's one live part (Vercel Python function, copied to site/api/model.py by build_site_data.py):
Muse model calls for the "Check my isolation" view. POST /api/model {op, ...}:

- op "resolve" {text | audio}: a worker's request -> one of the recorded confirmed plans (Muse Voice
  Transcribe for audio, then Muse Spark), the same code as the lab API's /api/checks/resolve.
- op "voice" {transcript | audio, detail}: a step command -> intent + read-back (zerostate.api.voice).
  `detail` is the page's own rehearsal state; it only shapes the read-back text sent back to that page.
- op "explain" {session, question}: "Why?" over a recorded session's logged findings (zerostate.llm.explain).

Read only: the plant data on the site is recorded; nothing here marks, verifies, reopens, signs or moves a
plant, and the function has no store to write to. MODEL_API_KEY comes from the Vercel project's environment
only; it is never logged or returned. Without it every op answers 503 and the page falls back to the plan
picker and typed steps. Calls go straight to api.meta.ai (Vercel has no lab proxy); the credit ledger lives
in the instance's /tmp, so ZS_BUDGET_USD (default 3) is a per-instance runaway stop, not an account cap.
"""

import base64
import binascii
import json
import os
import re
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "_zs"))  # the copies of src/zerostate modules made by build_site_data.py
os.environ.setdefault("ZS_CREDITS", "/tmp/zs_credits.jsonl")
os.environ.setdefault("ZS_BUDGET_USD", "3")

from zerostate import wording
from zerostate.api import voice
from zerostate.llm import client as model
from zerostate.llm.client import ModelUnavailable
from zerostate.llm.explain import explain
from zerostate.llm.resolve import resolve

DATA = HERE.parent / "data"
MAX_BODY = 700_000  # bytes of request JSON: 15 s of 16 kHz mono WAV in base64 fits
MAX_AUDIO_S = 15
MAX_TEXT = 500
SID = re.compile(r"[\w-]{1,80}")
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class BadInput(ValueError):
    pass


def _audio(b64) -> bytes:
    try:
        wav = base64.b64decode(str(b64), validate=True)
    except (binascii.Error, ValueError):
        raise BadInput("audio is not base64") from None
    if len(wav) > 44 + MAX_AUDIO_S * 32000:
        raise BadInput(f"recording longer than {MAX_AUDIO_S} s")
    return wav


def _text(v) -> str:
    return str(v or "").strip()[:MAX_TEXT]


def plans() -> list[dict]:
    return json.loads((DATA / "checks" / "plans.json").read_text(encoding="utf-8"))


def run(op: str, body: dict, opener=DIRECT) -> dict:
    if op == "resolve":
        ps, text, asr = plans(), _text(body.get("text")), None
        if body.get("audio"):
            kw = sorted({w for p in ps for w in (p["equipment"], p["plant"]) if w})
            text, asr = _text(model.transcribe(_audio(body["audio"]), "site_check_request", opener=opener, keywords=kw)), model.ASR
        r = resolve(text, ps, opener=opener)
        return {"text": text, "asr": asr, "plans": ps, "plan": next((p for p in ps if p["id"] == r["plan_id"]), None),
                "reason": r["reason"]}
    if op == "voice":
        d = body.get("detail") if isinstance(body.get("detail"), dict) else None
        transcript, asr = _text(body.get("transcript")), body.get("asr") or "typed"
        if body.get("audio"):
            try:
                transcript = _text(model.transcribe(_audio(body["audio"]), "site_voice_command", opener=opener,
                                                    keywords=voice.voice_keywords((d or {}).get("plan"))))
                asr = model.ASR
            except ModelUnavailable:
                return {"transcript": "", "asr": None, "intent": "unknown", "k": None,
                        "read_back": "I could not transcribe that here. Type the step instead."}
        try:
            intent, k, read_back = voice.answer(transcript, d)
        except (KeyError, TypeError, AttributeError):  # a detail the page made up: answer without it
            intent, k, read_back = voice.answer(transcript, None)
        if wording.hits(read_back):
            intent, k, read_back = "unknown", None, "I did not catch that."
        return {"transcript": transcript, "asr": str(asr)[:40], "intent": intent, "k": k, "read_back": read_back}
    if op == "explain":
        sid = str(body.get("session") or "")
        p = DATA / "sessions" / sid / "detail.json"
        if not SID.fullmatch(sid) or not p.is_file():
            raise BadInput("no such recorded session")
        return explain(_text(body.get("question")), json.loads(p.read_text(encoding="utf-8")), opener=opener)
    raise BadInput("op must be resolve, voice or explain")


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, obj: dict) -> None:
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return self._send(413 if n else 400, {"error": "bad_input", "detail": "request body missing or too large"})
        try:
            body = json.loads(self.rfile.read(n))
            if not isinstance(body, dict):
                raise BadInput("body must be a JSON object")
            return self._send(200, run(str(body.get("op")), body))
        except ModelUnavailable as e:
            return self._send(503, {"error": "model_unavailable", "detail": str(e)})
        except (BadInput, json.JSONDecodeError) as e:
            return self._send(400, {"error": "bad_input", "detail": str(e)})

    def do_GET(self):
        return self._send(405, {"error": "method", "detail": "POST only"})

    def log_message(self, *args):  # request lines carry nothing secret, but keep the function quiet
        pass
