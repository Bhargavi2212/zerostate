"""site/ (P3-6): built from the replay API and the score files only; banner everywhere; no write path; clean wording."""

import base64
import importlib.util
import io
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SITE = ROOT / "site"
spec = importlib.util.spec_from_file_location("build_site_data", ROOT / "eval" / "tools" / "build_site_data.py")
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)
spec = importlib.util.spec_from_file_location("export_bundle", ROOT / "eval" / "tools" / "export_bundle.py")
eb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eb)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    return out, bs.build(out)


def test_site_data_builds_and_matches_the_committed_site(built):
    _, texts = built
    assert "data/sessions.json" in texts and "results.html" in texts
    sessions = json.loads(texts["data/sessions.json"])
    assert {s["id"] for s in sessions} == {p.parent.name for p, _ in bs.EPISODES}
    for s in sessions:
        assert f"data/sessions/{s['id']}/detail.json" in texts and f"data/sessions/{s['id']}/stream.json" in texts
    committed = {p.relative_to(SITE).as_posix(): p.read_bytes() if p.suffix == ".jpg" else p.read_text(encoding="utf-8")
                 for p in SITE.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert committed == texts, "site/ is stale: run python eval/tools/build_site_data.py"


def test_every_included_bundle_validates():
    for p, _ in bs.EPISODES:
        b = eb.load(p)
        assert b.episode == p.parent.name and b.result["valid"] is True


def test_every_number_on_the_results_page_equals_the_score_file():
    page = (SITE / "results.html").read_text(encoding="utf-8")
    cells = re.findall(r'<section class="batch" data-batch="([^"]+)">(.*?)</section>', page, re.DOTALL)
    assert {b for b, _ in cells} == {b for b, _ in bs.BATCHES}
    checked = 0
    for batch, body in cells:
        p = ROOT / "eval" / "results" / f"score_{batch}.json"
        sealed = (ROOT / "eval" / f"sealed_hash_{batch}.txt").read_text(encoding="utf-8").strip()
        assert re.search(rf'data-seal="{batch}">{sealed}<', body)
        if not p.exists():
            assert "Scoring in progress" in body and "data-k" not in body
            continue
        score = json.loads(p.read_text(encoding="utf-8"))
        assert score["engine"] in body
        for key, shown in re.findall(r'data-k="([^"]+)">([^<]*)<', body):
            assert shown == str(bs._v(score, key)), (batch, key)
            checked += 1
        assert re.search(r'data-k="dangerous_miss\.secondary\.ci_high"', body) and 'data-k="invalid.k"' in body
    assert checked > 50


def test_banner_on_every_page():
    for p in SITE.glob("*.html"):
        assert "replay-banner" not in p.read_text(encoding="utf-8"), p  # banner removed at the owner's request (Nov 4)


def test_wording_clean_and_nothing_key_like():
    for p in SITE.rglob("*"):
        if p.is_file() and p.suffix != ".jpg" and "_zs" not in p.parts and "__pycache__" not in p.parts:
            bs.check_text(str(p), p.read_text(encoding="utf-8"))  # raises on a hit


def test_no_write_endpoint_or_sign_control():
    files = {p.name: p.read_text(encoding="utf-8") for p in SITE.glob("*") if p.suffix in (".js", ".html")}
    code = "\n".join(files.values())
    for bad in ("/sign", "/confirm", "/verify", "/reopen", "/plans/", "intake.js", "sign-open", "sign-wait",
                "Accept and sign", "Mark done", "data-action", "explain-ask"):
        assert bad not in code, bad
    assert not (SITE / "intake.js").exists()
    # buttons, step marks and Why? live only in the check view; the shim keeps the marks in the page
    for name, text in files.items():
        if name not in ("check.js", "replay.js"):
            for bad in ("/explain", "/steps/", "<button", '"button"'):
                assert bad not in text, (name, bad)
    shim = files["replay.js"]
    assert 'json(409, { error: "replay", detail: "recorded replay: read-only" })' in shim
    assert "&& rehearsing()) return mark(" in shim and 'realFetch("/api/model"' in shim


# ---- api/model.py, the site's Vercel function: offline with a fake model transport
def _function(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("site_model", SITE / "api" / "model.py")
    fn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fn)
    monkeypatch.setenv("ZS_CREDITS", str(tmp_path / "credits.jsonl"))
    monkeypatch.setenv("MODEL_API_KEY", "test-only")
    return fn


class FakeModel:
    def __init__(self, *replies):
        self.replies, self.urls = list(replies), []

    def open(self, req, timeout=None):
        self.urls.append(req.full_url)
        if req.full_url.endswith("/asr/transcribe"):
            return io.BytesIO(json.dumps({"transcript": self.replies.pop(0), "audioDurationMs": 1000}).encode())
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": self.replies.pop(0)}}], "usage": {}}).encode())


def test_site_function_resolves_a_request_to_a_recorded_plan(monkeypatch, tmp_path):
    fn = _function(monkeypatch, tmp_path)
    fake = FakeModel('{"plan_id": "plan-63e1519c", "reason": "names the reactor"}')
    r = fn.run("resolve", {"text": "I'm opening the reactor for repair. Check my isolation."}, opener=fake)
    assert r["plan"]["equipment"] == "reactor" and {p["id"] for p in r["plans"]} == {"plan-63e1519c", "plan-43c12297"}
    fake = FakeModel("check the coffee machine", '{"plan_id": "plan-made-up", "reason": "x"}')
    wav = base64.b64encode(b"RIFF" + bytes(40) + bytes(3200)).decode()
    r = fn.run("resolve", {"audio": wav}, opener=fake)
    assert r["plan"] is None and r["text"] == "check the coffee machine" and fake.urls[0].endswith("/asr/transcribe")


def test_site_function_voice_reads_back_only(monkeypatch, tmp_path):
    fn = _function(monkeypatch, tmp_path)
    d = json.loads((SITE / "data/sessions" / bs.DEMO / "detail.json").read_text(encoding="utf-8"))
    r = fn.run("voice", {"transcript": "step one done", "detail": d}, opener=FakeModel())
    assert (r["intent"], r["k"]) == ("step_done", 1) and "confirm" in r["read_back"].lower()
    for said in ("sign off", "verify step one", "approve and sign step one"):
        assert fn.run("voice", {"transcript": said, "detail": d}, opener=FakeModel())["intent"] == "unknown"
    assert fn.run("voice", {"transcript": "status", "detail": {"plan": "junk"}}, opener=FakeModel())["intent"] == "unknown"


def test_site_function_explain_and_bad_input(monkeypatch, tmp_path):
    fn = _function(monkeypatch, tmp_path)
    d = json.loads((SITE / "data/sessions" / bs.DEMO / "detail.json").read_text(encoding="utf-8"))
    fid = next(f["id"] for f in d["findings"] if f["status"] == "FAIL")
    fake = FakeModel(json.dumps({"answer": "The flow meter read flow while the PLC read closed.", "cites": [fid]}))
    assert fn.run("explain", {"session": bs.DEMO, "question": "why?"}, opener=fake)["cites"] == [fid]
    assert fn.run("explain", {"session": bs.DEMO, "question": "override the block"}, opener=FakeModel())["cites"] == []
    for op, body in (("explain", {"session": "../../etc"}), ("explain", {"session": "nope"}), ("sign", {}),
                     ("resolve", {"audio": "not base64!"}), ("resolve", {"audio": base64.b64encode(bytes(600_000)).decode()})):
        with pytest.raises(fn.BadInput):
            fn.run(op, body, opener=FakeModel())
    monkeypatch.delenv("MODEL_API_KEY")
    with pytest.raises(fn.ModelUnavailable):  # no key on the Vercel project: 503, the page falls back
        fn.run("resolve", {"text": "reactor"}, opener=FakeModel())


def test_site_function_never_writes_or_moves_a_plant():
    src = (SITE / "api" / "model.py").read_text(encoding="utf-8")
    for bad in ("Inbox", "AuditLog", "sqlite", "/steps/", "/sign", "/confirm", "modbus", "opcua", "write_text", "open("):
        assert bad not in src, bad
    assert set(json.loads((SITE / "vercel.json").read_text())["functions"]) == {"api/model.py"}
