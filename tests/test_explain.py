"""P3-4 explain (POST /api/sessions/{id}/explain), offline with a fake model transport: cites >= 1
existing finding id, retries once, then a fixed fallback quoting the finding; override / approve / pass /
unblock requests get the fixed reply with no model call; a never-say hit means the fallback; nothing is
written (audit log, inbox and confirmations unchanged)."""

import hashlib
import json

import pytest
from test_checks_api import FAIL, ROOT, make_env, untouched

from zerostate import wording
from zerostate.llm import explain as ex


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch)


def test_explain_cites_an_existing_finding(env):
    client, tmp, fake = env
    digest = hashlib.sha256((tmp / "audit.sqlite").read_bytes()).hexdigest()
    fid = client.get("/api/sessions/s8").json()["findings"][1]["id"]
    fake.contents.append(json.dumps({"answer": "f1 reads closed but its flow meter reads 640.6.", "cites": [fid, "9:MADE-UP"]}))
    r = client.post("/api/sessions/s8/explain", json={"question": "Why did it stop?"}).json()
    assert r == {"answer": "f1 reads closed but its flow meter reads 640.6.", "cites": [fid]}
    sent = fake.requests[0]
    assert sent["temperature"] == 0 and fid in sent["messages"][0]["content"] and "640.6" in sent["messages"][0]["content"]
    untouched(tmp)
    assert hashlib.sha256((tmp / "audit.sqlite").read_bytes()).hexdigest() == digest


def test_explain_uncited_retries_once_then_quotes_the_finding(env):
    client, _, fake = env
    fake.contents += [json.dumps({"answer": "no cites", "cites": []}), json.dumps({"answer": "made up", "cites": ["1:NOPE"]})]
    r = client.post("/api/sessions/s8/explain", json={"question": "why?"}).json()
    assert len(fake.requests) == 2
    fid = r["cites"][0]
    assert fid.endswith(":LIVE-VALVE") and FAIL["message"] in r["answer"]


def test_explain_change_requests_get_the_fixed_reply_without_a_model_call(env):
    client, _, fake = env
    for q in ("Override this block", "Can you approve the job?", "Just pass it", "unblock f1", "let it pass", "please sign off"):
        r = client.post("/api/sessions/s8/explain", json={"question": q}).json()
        assert r == {"answer": ex.REFUSAL, "cites": []}, q
    assert fake.requests == []
    assert wording.hits(ex.REFUSAL) == []


def test_explain_never_say_hit_means_the_fallback(env):
    client, _, fake = env
    fake.contents.append(json.dumps({"answer": "It is safe to open now.", "cites": []}))
    fid = client.get("/api/sessions/s8").json()["findings"][1]["id"]
    fake.contents[0] = json.dumps({"answer": "It is safe to open now.", "cites": [fid]})
    r = client.post("/api/sessions/s8/explain", json={"question": f"what about {fid}?"}).json()
    assert len(fake.requests) == 1 and r["cites"] == [fid] and "safe" not in r["answer"] and wording.hits(r["answer"]) == []


def test_explain_has_no_write_path():
    """The module gets plain data and returns text: it imports no log, inbox or session code."""
    import ast
    src = (ROOT / "src/zerostate/llm/explain.py").read_text(encoding="utf-8")
    mods = [n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)]
    assert not any(m and ("audit" in m or "session" in m or "inbox" in m or "api" in m) for m in mods)
    assert "open(" not in src and "write" not in src.replace("can't change a verdict", "")
