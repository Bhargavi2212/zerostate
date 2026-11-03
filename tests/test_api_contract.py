"""P2-9 API contract (docs/API.md), offline: every endpoint returns its schema, the API cannot write the
audit log, human actions only add inbox rows, and the voice route has no way to sign.
tmp dirs only; model routes use a fake opener (never the Meta API)."""

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_importer_gate import HEADER, P2_ROWS, FakeOpener, reply

from zerostate.api import server
from zerostate.audit.log import AuditLog
from zerostate.config import load_thresholds

ROOT = Path(__file__).parents[1]
DRAFT_KEYS = {"id", "route", "plant", "list", "transcript", "plan_hash", "findings", "unresolved", "defaults"}
STATUS_KEYS = {"state", "steps", "verdict", "verdict_with_camera", "stamp", "refused", "camera_pending"}
FINDING = {"rule_id": "LIVE-ALIVE", "rule_version": "2", "status": "PASS", "message": "pressure moved", "refs": [], "path": []}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("ZS_CREDITS", str(tmp_path / "credits.jsonl"))
    config = tmp_path / "config" / "p2_gasline"
    config.mkdir(parents=True)
    shutil.copy(ROOT / "plants/p2_gasline/plant_map.yaml", config)
    log = AuditLog(tmp_path / "audit.sqlite")
    for kind, payload in [("ready", {}), ("step_done", {"k": 1, "by": "A"}),
                          ("evaluation", {"source": "step", "step": 1, "findings": [FINDING]}),
                          ("verdict", {"verdict": "BLOCKED", "reasons": ["x"]})]:
        log.append("s1", kind, payload)
    log.close()
    run = tmp_path / "data" / "runs" / "s1"
    run.mkdir(parents=True)
    (run / "signals.jsonl").write_text("".join(json.dumps({"t": t, "PT-211": [200.0, 1, "GOOD"]}) + "\n" for t in range(3)))
    opener = FakeOpener()
    app = server.create_app(tmp_path / "data", tmp_path / "audit.sqlite", tmp_path / "config",
                            load_thresholds(ROOT / "plants/p2_gasline/thresholds.yaml"), opener=opener, poll_s=0)
    return TestClient(app), tmp_path, opener


def csv_import(client, rows):
    body = (HEADER + "\n".join(rows) + "\n").encode()
    return client.post("/api/plans/import", data={"route": "csv", "plant": "p2_gasline"},
                       files={"file": ("export.csv", body, "text/csv")})


def inbox_rows(tmp) -> list[tuple]:
    p = tmp / "data" / "inbox.sqlite"
    if not p.exists():
        return []
    db = sqlite3.connect(p)
    try:
        return db.execute("SELECT session, kind, payload_json FROM inbox ORDER BY id").fetchall()
    finally:
        db.close()


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_plant_map(env):
    client, _, _ = env
    m = client.get("/api/plants/p2_gasline/map").json()
    assert {"nodes", "pipes", "instruments", "plan_defaults"} <= set(m)
    assert client.get("/api/plants/nope/map").status_code == 404
    r = client.get("/api/plants/..%2F..%2Fetc/map")
    assert r.status_code in (400, 404) and set(r.json()) == {"error", "detail"}


def test_csv_import_get_put_and_confirm(env):
    client, tmp, _ = env
    d = csv_import(client, P2_ROWS).json()
    assert set(d) == DRAFT_KEYS and d["route"] == "csv" and d["unresolved"] == [] and len(d["plan_hash"]) == 64
    assert d["defaults"] == [{"field": "hold_minutes", "value": 10.0, "source": "plant default"}]
    assert all({"rule_id", "rule_version", "status", "message", "refs", "path"} == set(f) for f in d["findings"])
    assert client.get(f"/api/plans/drafts/{d['id']}").json() == d

    edited = {**d["list"], "points": [{**d["list"]["points"][1], "isolation_type": None}, *d["list"]["points"][:1]]}
    e = client.put(f"/api/plans/drafts/{d['id']}", json={"list": edited}).json()
    assert set(e) == DRAFT_KEYS and e["unresolved"] and e["plan_hash"] is None
    r = client.post(f"/api/plans/drafts/{d['id']}/confirm", json={"by": "Owner", "role": "issuer"})
    assert r.status_code == 409 and set(r.json()) == {"error", "detail"}  # unresolved: not confirmable
    assert not (tmp / "data" / "plans").exists()

    client.put(f"/api/plans/drafts/{d['id']}", json={"list": d["list"]})
    rec = client.post(f"/api/plans/drafts/{d['id']}/confirm", json={"by": "Owner", "role": "issuer"}).json()
    assert set(rec) == {"plan_hash", "by", "role", "date"} and rec["plan_hash"] == d["plan_hash"]


def test_confirm_refuses_while_unresolved_and_needs_issuer(env):
    client, _, _ = env
    rows = [P2_ROWS[0], P2_ROWS[1].replace(",proved,A-02", ",,A-02"), *P2_ROWS[2:]]  # closed point, no isolation type
    d = csv_import(client, rows).json()
    assert d["unresolved"] == ["point 2 (XV-203): isolation_type is unclear"]
    assert client.post(f"/api/plans/drafts/{d['id']}/confirm", json={"by": "Owner", "role": "issuer"}).status_code == 409
    assert client.post(f"/api/plans/drafts/{d['id']}/confirm", json={"by": "Owner", "role": "receiver"}).status_code == 400
    assert client.post(f"/api/plans/drafts/{d['id']}/confirm", json={"by": " ", "role": "issuer"}).status_code == 400


def test_text_and_image_routes_with_a_fake_model(env, monkeypatch):
    client, _, opener = env
    monkeypatch.setenv("MODEL_API_KEY", "fake-key-for-tests")  # pragma: allowlist secret
    text = "F-210: close XV-201 (proved), then XV-203 (proved). BV-202 proves both. Vent VV-213, hold 10."
    opener.contents = [reply()]
    d = client.post("/api/plans/import", data={"route": "text", "plant": "p2_gasline", "text": text}).json()
    assert set(d) == DRAFT_KEYS and d["route"] == "text" and d["transcript"] is None

    opener.contents = [json.dumps({"text": text}), reply()]
    d = client.post("/api/plans/import", data={"route": "image", "plant": "p2_gasline"},
                    files={"file": ("sheet.png", b"\x89PNG not really", "image/png")}).json()
    assert set(d) == DRAFT_KEYS and d["route"] == "image" and d["transcript"] == text


def test_errors_are_json_with_the_contract_codes(env):
    client, _, _ = env
    cases = [
        (client.post("/api/plans/import", data={"route": "text", "plant": "p2_gasline", "text": "close XV-201"}), 503),
        (client.post("/api/plans/import", data={"route": "fax", "plant": "p2_gasline", "text": "x"}), 400),
        (csv_import(client, ["WO-1,F-210,XV-201,shut,1,proved,A-01,VV-213,,"]), 400),
        (client.get("/api/plans/drafts/0123456789ab"), 404),
        (client.get("/api/sessions/nope"), 404),
        (client.post("/api/sessions/nope/sign", json={"by": "A", "role": "receiver"}), 404),
    ]
    for r, code in cases:
        assert r.status_code == code and set(r.json()) == {"error", "detail"}, r.text


def test_session_status_and_stream(env):
    client, tmp, _ = env
    s = client.get("/api/sessions/s1").json()
    assert set(s) == STATUS_KEYS and s["steps"] == {"1": "PASS"} and s["verdict"] == "BLOCKED"

    log = AuditLog(tmp / "audit.sqlite")
    log.append("s1", "signature", {"by": "R", "role": "receiver"})  # ends the stream
    log.close()
    body = client.get("/api/sessions/s1/stream").text
    kinds = [ln.split(": ", 1)[1] for ln in body.splitlines() if ln.startswith("event: ")]
    assert kinds == ["step", "evaluation", "finding", "verdict", "signals"]
    assert json.loads(body.split("event: signals\ndata: ")[1].split("\n")[0])["t"] == 2  # newest sample only


def test_steps_and_sign_only_add_inbox_rows(env):
    client, tmp, _ = env
    before = digest(tmp / "audit.sqlite")
    calls = [("steps/2/done", {"by": "A"}), ("steps/2/verify", {"by": "B"}),
             ("steps/2/reopen", {"by": "A", "reason": "inch and test"}), ("sign", {"by": "R", "role": "receiver", "note": "ok"})]
    for path, body in calls:
        assert client.post(f"/api/sessions/s1/{path}", json=body).json() == {"queued": True}
    assert [(s, k) for s, k, _ in inbox_rows(tmp)] == [("s1", "step_done"), ("s1", "step_verify"),
                                                        ("s1", "step_reopen"), ("s1", "sign")]
    assert json.loads(inbox_rows(tmp)[2][2]) == {"k": 2, "by": "A", "reason": "inch and test"}
    assert digest(tmp / "audit.sqlite") == before
    assert client.post("/api/sessions/s1/sign", json={"by": "R", "role": "boss"}).status_code == 400


def test_api_opens_the_audit_log_read_only_and_a_write_fails(env, monkeypatch):
    client, tmp, _ = env
    modes = []

    class Spy(AuditLog):
        def __init__(self, path, read_only=False):
            modes.append(read_only)
            super().__init__(path, read_only)

    monkeypatch.setattr(server, "AuditLog", Spy)
    client.get("/api/sessions/s1")
    client.post("/api/sessions/s1/steps/2/done", json={"by": "A"})
    assert modes and all(modes)

    ro = AuditLog(tmp / "audit.sqlite", read_only=True)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ro.append("s1", "verdict", {"verdict": "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"})
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ro.db.execute("INSERT INTO events (ts, session, kind, payload_json, prev_hash, hash) VALUES (1,1,1,1,1,1)")
    ro.close()
    assert len(AuditLog(tmp / "audit.sqlite").events("s1")) == 4


def test_voice_reads_back_only_and_can_never_reach_sign(env):
    client, tmp, _ = env
    r = client.post("/api/voice/command", json={"audio": "c2lnbiBvZmY="}).json()  # "sign off"
    assert set(r) == {"transcript", "intent", "k", "read_back"} and r["intent"] == "unknown"
    assert inbox_rows(tmp) == []
    # no code path: the handler names nothing that writes the inbox or signs
    names = set(server.voice_command.__code__.co_names)
    assert not names & {"Inbox", "queue", "put", "sign", "confirm", "step_done"}
    assert server.voice_command.__module__ == server.__name__
    routes = {r.path: r.endpoint for r in client.app.routes if hasattr(r, "endpoint")}
    assert routes["/api/voice/command"] is server.voice_command


def test_explain_stub(env):
    client, _, _ = env
    r = client.post("/api/sessions/s1/explain", json={"question": "why blocked?"}).json()
    assert set(r) == {"answer", "cites"} and isinstance(r["cites"], list)
