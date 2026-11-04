"""P3-3 "Check my isolation", offline with a fake model transport (never the Meta API).

POST /api/checks/resolve: a request -> one confirmed plan by id, or none; a made-up id is none; it is
read-only (no inbox row, no session, no confirmation, audit log unchanged). The fixture (a throwaway
config + data dir with one blocked session) is shared with tests/test_explain.py.
"""

import base64
import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zerostate.api import server
from zerostate.audit.log import AuditLog

ROOT = Path(__file__).parents[1]
P1_HASH = "63e1519c52f653b2607444e39baa63973b27cd867ec45c056d017f26e5f1bbc4"  # pragma: allowlist secret (a public plan hash)
FAIL = {"rule_id": "LIVE-VALVE", "rule_version": "2", "status": "FAIL", "refs": ["f1_flow", "f1_valve_pos"], "path": [],
        "message": "flow through a valve reading closed: f1_flow = 640.6 while f1_valve_pos = 0.0 % (passing valve or false feedback)"}
PASS = {"rule_id": "LIVE-QUALITY", "rule_version": "1", "status": "PASS", "refs": [], "path": [],
        "message": "all witnesses fresh and in range"}


class Fake:
    """Model transport stand-in: one canned chat reply (or transcript) per call; records each request."""

    def __init__(self, *contents):
        self.contents, self.requests = list(contents), []

    def open(self, req, timeout=None):
        if req.full_url.endswith("/asr/transcribe"):
            self.requests.append({"asr": True})
            return io.BytesIO(json.dumps({"transcript": self.contents.pop(0), "audioDurationMs": 2000}).encode())
        self.requests.append(json.loads(req.data))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": self.contents.pop(0)}}],
                                      "usage": {"prompt_tokens": 100, "completion_tokens": 20}}).encode())


def make_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "fake-key-for-tests")  # pragma: allowlist secret
    monkeypatch.setenv("ZS_CREDITS", str(tmp_path / "credits.jsonl"))
    for plant, files in (("p1_grfics", ("plant_map.yaml", "envelope.yaml", "confirmed.yaml")),
                         ("p2_gasline", ("plant_map.yaml", "plan.yaml", "confirmed.yaml"))):
        (tmp_path / "config" / plant).mkdir(parents=True)
        for f in files:
            shutil.copy(ROOT / "plants" / plant / f, tmp_path / "config" / plant)
    import yaml
    plan = yaml.safe_load((ROOT / "plants/p1_grfics/envelope.yaml").read_text(encoding="utf-8"))
    log = AuditLog(tmp_path / "audit.sqlite")
    for kind, payload in [("session_start", {"plan": plan, "plan_hash": P1_HASH}), ("ready", {}),
                          ("evaluation", {"source": "step", "step": 2, "findings": [PASS, FAIL]}),
                          ("verdict", {"verdict": "BLOCKED", "reasons": [f"LIVE-VALVE: {FAIL['message']}"]})]:
        log.append("s8", kind, payload)
    log.close()
    (tmp_path / "data").mkdir()
    fake = Fake()
    app = server.create_app(tmp_path / "data", tmp_path / "audit.sqlite", tmp_path / "config", {}, opener=fake, poll_s=0)
    return TestClient(app), tmp_path, fake


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch)


def untouched(tmp: Path):
    """Read-only: no inbox, no drafts or confirmed plans written, no confirmed.yaml changed."""
    assert not (tmp / "data" / "inbox.sqlite").exists() and not (tmp / "data" / "plans").exists()
    for plant in ("p1_grfics", "p2_gasline"):
        assert (tmp / "config" / plant / "confirmed.yaml").read_bytes() == (ROOT / "plants" / plant / "confirmed.yaml").read_bytes()


def test_plans_lists_only_confirmed_plans(env):
    client, _, fake = env
    plans = client.get("/api/checks/plans").json()
    assert {p["plant"] for p in plans} == {"p1_grfics", "p2_gasline"}
    p1 = next(p for p in plans if p["plant"] == "p1_grfics")
    assert p1["plan_hash"] == P1_HASH and p1["id"] == "plan-63e1519c" and p1["equipment"] == "reactor"
    assert fake.requests == []


def test_resolve_good_pick(env):
    client, tmp, fake = env
    digest = hashlib.sha256((tmp / "audit.sqlite").read_bytes()).hexdigest()
    fake.contents.append(json.dumps({"plan_id": "plan-63e1519c", "reason": "the request names the reactor"}))
    r = client.post("/api/checks/resolve", json={"text": "I'm about to open the reactor for repair. Check my isolation."}).json()
    assert r["plan"]["plan_hash"] == P1_HASH and r["reason"] == "the request names the reactor" and len(r["plans"]) == 2
    body = fake.requests[0]
    assert body["temperature"] == 0 and "plan-63e1519c" in body["messages"][0]["content"] and "plan-43c12297" in body["messages"][0]["content"]
    untouched(tmp)
    assert hashlib.sha256((tmp / "audit.sqlite").read_bytes()).hexdigest() == digest


def test_resolve_none(env):
    client, tmp, fake = env
    fake.contents.append(json.dumps({"plan_id": None, "reason": "the request does not name any listed equipment"}))
    r = client.post("/api/checks/resolve", json={"text": "check my isolation"}).json()
    assert r["plan"] is None and r["reason"] == "the request does not name any listed equipment" and len(r["plans"]) == 2
    untouched(tmp)


def test_resolve_made_up_id_is_none(env):
    client, tmp, fake = env
    fake.contents.append(json.dumps({"plan_id": "plan-deadbeef", "reason": "the boiler"}))
    r = client.post("/api/checks/resolve", json={"text": "check the boiler"}).json()
    assert r["plan"] is None and r["reason"] == "the model named a plan that is not on the list"
    fake.contents.append(json.dumps({"plan_id": P1_HASH, "reason": "a hash is not an id"}))  # close, but not an id on the list
    assert client.post("/api/checks/resolve", json={"text": "reactor"}).json()["plan"] is None
    untouched(tmp)


def test_resolve_audio_goes_through_muse_transcribe(env):
    client, tmp, fake = env
    fake.contents += ["I'm about to open the reactor", json.dumps({"plan_id": "plan-63e1519c", "reason": "reactor"})]
    r = client.post("/api/checks/resolve", json={"audio": base64.b64encode(b"RIFF....WAVE").decode()}).json()
    assert r["text"] == "I'm about to open the reactor" and r["asr"] == "muse-voice-transcribe-1.0" and r["plan"]["plant"] == "p1_grfics"
    assert fake.requests[0] == {"asr": True}
    assert client.post("/api/checks/resolve", json={}).status_code == 400
    untouched(tmp)


def test_resolve_without_the_model_is_503(env, monkeypatch):
    client, _, _ = env
    monkeypatch.delenv("MODEL_API_KEY")
    assert client.post("/api/checks/resolve", json={"text": "reactor"}).status_code == 503


def test_voice_audio_goes_through_muse_transcribe_and_only_reads_back(env):
    """Live step mode: a spoken step is transcribed by Muse Voice Transcribe (plan valve names as keywords),
    parsed by the existing rules and read back; nothing is marked (no inbox row)."""
    client, tmp, fake = env
    fake.contents.append("step one done")
    r = client.post("/api/voice/command", json={"session": "s8", "audio": base64.b64encode(b"RIFF....WAVE").decode()}).json()
    assert (r["transcript"], r["asr"], r["intent"], r["k"]) == ("step one done", "muse-voice-transcribe-1.0", "step_done", 1)
    assert "confirm" in r["read_back"].lower() and fake.requests == [{"asr": True}]
    untouched(tmp)
