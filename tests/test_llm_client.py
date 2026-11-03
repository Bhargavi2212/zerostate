"""llm/client.py offline: a fake opener stands in for the proxy and the Meta API."""

import io
import json
import urllib.error

import pytest
from pydantic import BaseModel

from zerostate.llm import client

KEY = "sk-test-not-a-real-key-0123456789"  # pragma: allowlist secret


class Reading(BaseModel):
    value: float | None
    readable: bool


class Reply(io.BytesIO):
    def __iter__(self):
        return iter(self.getvalue().splitlines(keepends=True))


class FakeOpener:
    def __init__(self, *bodies):
        self.bodies, self.requests = list(bodies), []

    def open(self, req, timeout=None):
        self.requests.append(req)
        b = self.bodies.pop(0)
        if isinstance(b, Exception):
            raise b
        return Reply(b if isinstance(b, bytes) else json.dumps(b).encode())


def chat(content, tin=1000, tout=50):
    return {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": tin, "completion_tokens": tout}}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", KEY)
    monkeypatch.setenv("ZS_CREDITS", str(tmp_path / "credits.jsonl"))
    monkeypatch.setenv("ZS_BUDGET_USD", "75")
    return tmp_path / "credits.jsonl"


def test_spark_json_validates_and_logs_cost(env):
    op = FakeOpener(chat('```json\n{"value": 42.5, "readable": true}\n```'))
    r = client.spark_json([{"role": "user", "content": "read"}], Reading, "camera_read", opener=op)
    assert r == Reading(value=42.5, readable=True)
    line = json.loads(env.read_text())
    assert line["model"] == client.SPARK and line["purpose"] == "camera_read"
    assert line["usd"] == pytest.approx(1000 / 1e6 * 1.25 + 50 / 1e6 * 4.25, abs=1e-6)  # ledger keeps 6 decimals
    assert op.requests[0].full_url == client.BASE + "/chat/completions"


def test_spark_json_retries_once_then_fails(env):
    op = FakeOpener(chat("not json"), chat('{"value": "x"}'))
    with pytest.raises(client.ModelUnavailable, match="after a retry"):
        client.spark_json([], Reading, "camera_read", opener=op)
    assert len(env.read_text().splitlines()) == 2  # both calls cost money and are logged


def test_sam_boxes_parses_streamed_tokens(env):
    deltas = ["<|box;x1=10;y1=20;x2=30;", "y2=40;w=20;h=20;c=0.81|> <|box;x1=1;y1=2;x2=3;y2=4|>", "<|box;junk|>"]
    sse = b"".join(b"data: " + json.dumps({"type": "response.output_text.delta", "delta": d}).encode() + b"\n" for d in deltas)
    boxes = client.sam_boxes(b"\xff\xd8jpeg", "digital display", "camera_locate", opener=FakeOpener(sse + b"data: [DONE]\n"))
    assert boxes[0] == {"x1": 10, "y1": 20, "x2": 30, "y2": 40, "c": 0.81}
    assert boxes[1]["x2"] == 3 and len(boxes) == 2
    assert json.loads(env.read_text())["images"] == 1


def test_budget_refuses_before_calling(env, monkeypatch):
    env.write_text(json.dumps({"usd": 80.0}) + "\n")
    op = FakeOpener()
    with pytest.raises(client.ModelUnavailable, match="budget"):
        client.spark_json([], Reading, "x", opener=op)
    assert op.requests == []
    monkeypatch.setenv("ZS_BUDGET_USD", "100")  # raising the limit lets work continue
    client.spark_json([], Reading, "x", opener=FakeOpener(chat('{"value": null, "readable": false}')))


def test_key_only_in_the_header_never_in_errors_or_ledger(env):
    op = FakeOpener(chat('{"value": 1, "readable": true}'))
    client.spark_json([], Reading, "x", opener=op)
    assert op.requests[0].get_header("Authorization") == f"Bearer {KEY}"
    assert KEY not in json.dumps(op.requests[0].data.decode()) and KEY not in env.read_text()
    http = urllib.error.HTTPError(client.BASE, 401, f"bad key {KEY}", {"Authorization": KEY}, None)
    for err in (http, OSError(f"proxy refused Bearer {KEY}")):
        with pytest.raises(client.ModelUnavailable) as e:
            client.spark_json([], Reading, "x", opener=FakeOpener(err))
        assert KEY not in str(e.value) and e.value.__cause__ is None


def test_missing_key_refuses(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY")
    with pytest.raises(client.ModelUnavailable, match="not set"):
        client.spark_json([], Reading, "x", opener=FakeOpener())

def test_transcribe_sends_multipart_wav_and_logs_seconds(env):
    op = FakeOpener({"sessionId": "s", "transcript": "step one done", "audioDurationMs": 2900, "turns": []})
    assert client.transcribe(b"RIFFfakewav", "voice_test", opener=op) == "step one done"
    req = op.requests[0]
    assert req.full_url.endswith("/asr/transcribe") and req.get_header("Content-type").startswith("multipart/form-data")
    assert b'"model": "muse-voice-transcribe-1.0"' in req.data and b"RIFFfakewav" in req.data
    row = json.loads(env.read_text(encoding="utf-8").splitlines()[-1])
    assert row["model"] == "muse-voice-transcribe-1.0" and row["audio_ms"] == 2900 and row["usd"] == round(2 * 0.18 / 3600, 6)
    assert KEY not in env.read_text(encoding="utf-8")
