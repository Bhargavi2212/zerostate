"""P2-9 API contract (docs/API.md), offline: every endpoint returns its schema, the API cannot write the
audit log, human actions only add inbox rows, and the voice route has no way to sign.
tmp dirs only; model routes use a fake opener (never the Meta API)."""

import hashlib
import io
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
DETAIL_KEYS = {"id", "plant", "state", "started", "plan_hash", "plan", "confirmation", "assumptions", "plan_check_override",
               "steps", "findings", "verdict", "verdict_with_camera", "tracks", "stamp", "refused", "camera_pending", "signature"}
STEP_KEYS = {"k", "kind", "targets", "required_state", "marked_by", "marked_t", "verified_by", "verified_t", "reopened",
             "result", "finding_ids"}
SUMMARY_KEYS = {"id", "plant", "plan_hash", "started", "state", "verdict", "verdict_with_camera", "signed"}
FINDING = {"rule_id": "LIVE-ALIVE", "rule_version": "2", "status": "PASS", "message": "pressure moved", "refs": [], "path": []}
PLAN = {"plant": "p2_gasline", "assumptions": [{"text": "Positive isolation upstream assumed"}],
        "steps": [{"k": 1, "kind": "isolate", "targets": ["XV-201", "XV-203"], "required_state": 0.0},
                  {"k": 2, "kind": "vent_open", "target": "VV-213", "required_state": 100.0},
                  {"k": 3, "kind": "vent_close", "target": "VV-213", "required_state": 0.0},
                  {"k": 4, "kind": "final"}]}
START = {"plan": PLAN, "plan_hash": "a" * 64, "confirmation": {"plan_hash": "a" * 64, "by": "Owner", "role": "issuer", "date": "d"},
         "plan_check_override": "control-valve isolation accepted for live-evidence testbed"}
CAM_FINDING = {"rule_id": "LIVE-CAMERA", "rule_version": "1", "status": "FAIL", "message": "display 40 vs feedback 0",
               "refs": [], "path": []}


def frame_jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (90, 90, 90)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("ZS_CREDITS", str(tmp_path / "credits.jsonl"))
    config = tmp_path / "config" / "p2_gasline"
    config.mkdir(parents=True)
    shutil.copy(ROOT / "plants/p2_gasline/plant_map.yaml", config)
    jpg = frame_jpeg()
    sha = hashlib.sha256(jpg).hexdigest()
    reading = {"step": 1, "point": "XV-201", "tag": "camera", "t": 5.0, "value": 40.0, "readable": True, "note": None,
               "frame_sha256": sha, "box": [10, 10, 40, 30], "crop_hash": "0f", "feedback_at": 0.0}
    log = AuditLog(tmp_path / "audit.sqlite")
    for kind, payload in [("session_start", START), ("ready", {}), ("step_done", {"k": 1, "by": "eval-operator"}),
                          ("step_verify", {"k": 1, "by": "eval-verifier"}),
                          ("evaluation", {"source": "step", "step": 1, "findings": [FINDING]}),
                          ("verdict", {"verdict": "BLOCKED", "reasons": ["x"]}),
                          ("camera_capture", {"step": 1, "points": ["XV-201"]}),
                          ("camera_reading", reading),
                          ("evaluation", {"source": "camera", "step": 1, "point": "XV-201", "tag": "camera", "camera": "optional",
                                          "readings": [reading], "feedback": [[4.0, 0.0]], "findings": [CAM_FINDING],
                                          "verdict_after": "BLOCKED", "with_camera_after": "BLOCKED"}),
                          ("verdict", {"verdict": "BLOCKED", "track": "with_camera", "reasons": ["LIVE-CAMERA: y"]})]:
        log.append("s1", kind, payload)
    log.close()
    (tmp_path / "data" / "frames" / "s1").mkdir(parents=True)
    (tmp_path / "data" / "frames" / "s1" / f"{sha}.jpg").write_bytes(jpg)
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


def test_session_detail_list_and_stream(env):
    client, tmp, _ = env
    s = client.get("/api/sessions/s1").json()
    assert set(s) == DETAIL_KEYS and s["plant"] == "p2_gasline" and s["plan_hash"] == "a" * 64
    assert s["assumptions"] == ["Positive isolation upstream assumed"] and s["confirmation"]["by"] == "Owner"
    assert s["plan_check_override"] == START["plan_check_override"]
    assert all(set(st) == STEP_KEYS for st in s["steps"]) and [st["k"] for st in s["steps"]] == [1, 2, 3, 4]
    one = s["steps"][0]
    assert (one["marked_by"], one["verified_by"], one["result"]) == ("eval-operator", "eval-verifier", "PASS")
    assert one["targets"] == ["XV-201", "XV-203"] and one["finding_ids"] == ["5:LIVE-ALIVE", "9:LIVE-CAMERA"]
    assert s["steps"][1]["marked_by"] is None and s["steps"][1]["targets"] == ["VV-213"]
    assert [f["id"] for f in s["findings"]] == ["5:LIVE-ALIVE", "9:LIVE-CAMERA"]
    assert s["tracks"]["data_only"]["verdict"] == "BLOCKED" and s["tracks"]["data_only"]["reasons"] == ["x"]
    assert s["tracks"]["with_camera"]["verdict"] == "BLOCKED" and "LIVE-CAMERA: y" in s["tracks"]["with_camera"]["reasons"]
    assert s["camera_pending"] == 0 and s["signature"] is None and s["state"] == "ready"

    rows = client.get("/api/sessions").json()
    assert [set(r) for r in rows] == [SUMMARY_KEYS]
    assert rows[0]["id"] == "s1" and rows[0]["verdict"] == "BLOCKED" and rows[0]["signed"] is False

    log = AuditLog(tmp / "audit.sqlite")
    log.append("s1", "signature", {"by": "R", "role": "receiver", "outcome": "not_accepted"})  # ends the stream
    log.close()
    body = client.get("/api/sessions/s1/stream").text
    kinds = [ln.split(": ", 1)[1] for ln in body.splitlines() if ln.startswith("event: ")]
    assert kinds == ["session_start", "step", "step_verify", "evaluation", "finding", "verdict", "camera_reading",
                     "evaluation", "finding", "verdict", "signature", "signals"]
    findings = [json.loads(b.split("\n")[0]) for b in body.split("event: finding\ndata: ")[1:]]
    assert [(f["id"], f["eval_id"]) for f in findings] == [("5:LIVE-ALIVE", 5), ("9:LIVE-CAMERA", 9)]
    assert json.loads(body.split("event: signals\ndata: ")[1].split("\n")[0])["t"] == 2  # newest sample only
    assert client.get("/api/sessions").json()[0]["signed"] is True


def test_camera_evidence_frame_and_crop(env):
    client, _, _ = env
    c = client.get("/api/sessions/s1/camera/9").json()
    assert c["label"] == "idealised camera (renders the simulator's true state)"
    assert c["finding"]["id"] == "9:LIVE-CAMERA" and c["feedback"] == [[4.0, 0.0]]
    r = c["readings"][0]
    assert r["box"] == [10, 10, 40, 30] and r["value"] == 40.0 and r["feedback_at"] == 0.0
    frame = client.get(r["frame_url"])
    assert frame.headers["content-type"] == "image/jpeg" and hashlib.sha256(frame.content).hexdigest() == r["frame_sha256"]
    crop = client.get(r["crop_url"])
    assert crop.status_code == 200 and crop.content[:4] == b"\x89PNG"
    assert client.get("/api/sessions/s1/camera/5").status_code == 404  # a step evaluation, not a camera one
    assert client.get(f"/api/sessions/s1/frames/{'0' * 64}.jpg").status_code == 404
    assert client.get("/api/sessions/s1/frames/..%2F..%2Faudit.sqlite").status_code == 404


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
    assert json.loads(inbox_rows(tmp)[3][2])["outcome"] == "not_accepted"  # the default: never reads as approval
    assert digest(tmp / "audit.sqlite") == before
    assert client.post("/api/sessions/s1/sign", json={"by": "R", "role": "boss"}).status_code == 400
    r = client.post("/api/sessions/s1/sign", json={"by": "R", "role": "receiver", "outcome": "accepted"})
    assert r.status_code == 409 and len(inbox_rows(tmp)) == 4  # accepted needs both tracks at NO DISCREPANCY


def test_session_start_queues_a_confirmed_plan_only(env):
    client, tmp, _ = env
    body = {"plant": "p2_gasline", "plan_hash": "b" * 64, "by": "Owner", "plan_check_override": None}
    assert client.post("/api/sessions", json=body).status_code == 404  # nobody confirmed it
    assert client.post("/api/sessions", json={**body, "plan_hash": "nope"}).status_code == 400
    d = csv_import(client, P2_ROWS).json()
    client.post(f"/api/plans/drafts/{d['id']}/confirm", json={"by": "Owner", "role": "issuer"})  # tmp data dir only
    before = digest(tmp / "audit.sqlite")
    r = client.post("/api/sessions", json={**body, "plan_hash": d["plan_hash"]})
    assert r.status_code == 202 and r.json()["queued"] is True
    sid = r.json()["session"]
    assert server.NAME.fullmatch(sid)
    assert inbox_rows(tmp)[-1][:2] == (sid, "session_start") and json.loads(inbox_rows(tmp)[-1][2])["plan_hash"] == d["plan_hash"]
    assert digest(tmp / "audit.sqlite") == before


def test_test_name_cannot_confirm_or_sign_on_real_data(env, monkeypatch):
    client, tmp, _ = env
    d = csv_import(client, P2_ROWS).json()
    monkeypatch.setattr(server, "REAL_DATA", tmp / "data")  # this app's data dir now counts as the real /data
    r = client.post(f"/api/plans/drafts/{d['id']}/confirm", json={"by": "playwright-test", "role": "issuer"})
    assert r.status_code == 403 and r.json()["error"] == "test_name_on_real_data"
    r = client.post("/api/sessions/s1/sign", json={"by": "playwright-test", "role": "receiver"})
    assert r.status_code == 403 and inbox_rows(tmp) == [] and not (tmp / "data" / "plans").exists()
    monkeypatch.setattr(server, "REAL_DATA", Path("/data"))  # a throwaway dir: allowed
    assert client.post("/api/sessions/s1/sign", json={"by": "playwright-test", "role": "receiver"}).json() == {"queued": True}
    assert client.post(f"/api/plans/drafts/{d['id']}/confirm", json={"by": "playwright-test", "role": "issuer"}).status_code == 200


def test_api_opens_the_audit_log_read_only_and_a_write_fails(env, monkeypatch):
    client, tmp, _ = env
    modes = []

    class Spy(AuditLog):
        def __init__(self, path, read_only=False):
            modes.append(read_only)
            super().__init__(path, read_only)

    monkeypatch.setattr(server, "AuditLog", Spy)
    client.get("/api/sessions/s1")
    client.get("/api/sessions")
    client.post("/api/sessions/s1/steps/2/done", json={"by": "A"})
    assert modes and all(modes)

    ro = AuditLog(tmp / "audit.sqlite", read_only=True)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ro.append("s1", "verdict", {"verdict": "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"})
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ro.db.execute("INSERT INTO events (ts, session, kind, payload_json, prev_hash, hash) VALUES (1,1,1,1,1,1)")
    ro.close()
    assert len(AuditLog(tmp / "audit.sqlite").events("s1")) == 10


def voice(client, text, session="s1"):
    r = client.post("/api/voice/command", json={"session": session, "transcript": text, "asr": "browser-speech"})
    assert r.status_code == 200, r.text
    return r.json()


def test_voice_maps_a_step_only_from_its_number_or_every_target_and_state(env):
    client, tmp, _ = env
    r = voice(client, "step one done")
    assert set(r) == {"transcript", "asr", "intent", "k", "read_back"} and (r["intent"], r["k"]) == ("step_done", 1)
    assert "XV-201" in r["read_back"] and "confirm" in r["read_back"].lower()
    assert (voice(client, "XV 201 and XV-203 are closed")["intent"], voice(client, "XV 201 and XV-203 are closed")["k"]) == ("step_done", 1)
    assert voice(client, "XV-201 is closed")["intent"] == "unknown"  # not every target of step 1
    assert voice(client, "XV-201 and XV-203")["intent"] == "unknown"  # no state
    assert (voice(client, "vent VV-213 open")["k"], voice(client, "VV 213 shut")["k"]) == (2, 3)
    assert voice(client, "step 9 done")["intent"] == "unknown"
    assert [voice(client, w)["intent"] for w in ("yes", "cancel", "repeat", "status", "why is it blocked")] == \
           ["confirm", "cancel", "repeat", "status", "why"]
    assert "blocked" in voice(client, "status")["read_back"].lower() and voice(client, "why")["read_back"] == "x"
    assert inbox_rows(tmp) == []


def test_voice_reads_back_only_and_can_never_reach_sign(env):
    client, tmp, _ = env
    r = client.post("/api/voice/command", json={"audio": "c2lnbiBvZmY="}).json()  # "sign off"
    assert set(r) == {"transcript", "asr", "intent", "k", "read_back"} and r["intent"] == "unknown"
    for text in ("sign off", "verify step one", "reopen step one", "approve and sign step one"):
        assert voice(client, text)["intent"] == "unknown"
    assert client.post("/api/voice/command", json={"transcript": "yes"}).status_code == 400  # asr is required
    assert inbox_rows(tmp) == []
    # no code path: the handler names nothing that writes the inbox, signs, verifies or reopens
    for fn in (server.voice_command, server.parse_intent):
        names = set(fn.__code__.co_names)
        assert not names & {"Inbox", "queue", "put", "sign", "confirm", "step_done", "step_verify", "step_reopen"}
        assert fn.__module__ == server.__name__
    routes = {r.path: r.endpoint for r in client.app.routes if hasattr(r, "endpoint")}
    assert routes["/api/voice/command"] is server.voice_command


def test_explain_stub(env):
    client, _, _ = env
    r = client.post("/api/sessions/s1/explain", json={"question": "why blocked?"}).json()
    assert set(r) == {"answer", "cites"} and isinstance(r["cites"], list)

