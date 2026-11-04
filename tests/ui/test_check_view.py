"""P3-3 "Check my isolation" (#/check) in headless Chromium, against the real API app on a throwaway data
dir: an audit log built from the committed batch-2 S8 bundle (f1 feedback lies) plus a stopped copy that
ends NO DISCREPANCY, saved frames, and a fake model client (never the Meta API).

Checked: request -> plan -> session; rows tick in plan order with the logged statuses; the camera zoom
carries the exact caption, or "no camera frame for this check"; the STOP line names the deciding finding;
the no-discrepancy line is exact; "Why?" shows a cited answer; an unclear request lists the confirmed
plans; automated runs start muted; no sign control; never-say clean over all rendered text; never green."""

import gzip
import io
import json
import re
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from PIL import Image

from zerostate import wording
from zerostate.api import server
from zerostate.api.replay import bundle_events
from zerostate.audit.log import AuditLog

pytestmark = pytest.mark.ui
ROOT = Path(__file__).parents[2]
S8 = ROOT / "eval/results/bench/2/S8_seed1470975726_20261104T050105/bundle.json.gz"
Q = "I'm about to open the reactor for repair. I've locked out. Check my isolation."
NDF = "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"
PATHS: dict[str, Path] = {}


class FakeModel:
    def open(self, req, timeout=None):
        body = json.loads(req.data)
        system, user = body["messages"][0]["content"], body["messages"][-1]["content"]
        if "confirmed isolation plans" in system:
            out = {"plan_id": "plan-63e1519c", "reason": "the request names the reactor"} if "reactor" in user \
                else {"plan_id": "plan-ffffffff", "reason": "made up"}  # a made-up id must read as none
        else:
            fid = re.search(r"^(\d+:LIVE-VALVE) \| FAIL", system, re.MULTILINE).group(1)
            out = {"answer": "f1 reads closed while its flow meter reads flow.", "cites": [fid]}
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(out)}}], "usage": {}}).encode())


def jpeg(box) -> bytes:
    img = Image.new("RGB", (1600, 900), (70, 70, 70))
    img.paste((230, 230, 230), tuple(int(v) for v in box))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def check_server(tmp_path_factory, monkeypatch_module):
    tmp = tmp_path_factory.mktemp("zs-check-ui")
    data, config = tmp / "data", tmp / "config" / "p1_grfics"
    config.mkdir(parents=True)
    for f in ("plant_map.yaml", "envelope.yaml", "confirmed.yaml"):
        shutil.copy(ROOT / "plants/p1_grfics" / f, config)
    with gzip.open(S8, "rt", encoding="utf-8") as fh:
        b = json.load(fh)
    log = AuditLog(tmp / "audit.sqlite")
    for e in bundle_events(b):
        if e["kind"] == "evaluation" and e["payload"]["source"] == "camera":  # as the live camera track logs them
            e["payload"]["models"] = {"locate": "sam-3.1", "read": "muse-spark-1.3"}
        log.append("s8", e["kind"], e["payload"])
        if e["kind"] == "camera_reading" and e["payload"]["point"] == "f1" and e["payload"].get("box"):
            p = data / "frames" / "s8" / f"{e['payload']['frame_sha256']}.jpg"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(jpeg(e["payload"]["box"]))
    log.append("s8", "session_stopped", {})
    clean = [e for e in bundle_events(b) if e["kind"] in ("session_start", "ready", "step_done")]
    for e in clean:
        log.append("s0", e["kind"], e["payload"])
    log.append("s0", "evaluation", {"source": "step", "step": 2, "findings": [
        {"rule_id": "LIVE-VALVE", "rule_version": "2", "status": "PASS", "refs": [], "path": [], "message": "commanded state, position and flow agree with the plan"}]})
    unsaved = {"step": 2, "point": "f1", "tag": "f1_valve_pos", "t": 1.0, "value": 0.0, "readable": True, "note": None,
               "frame_sha256": "0" * 64, "box": [594, 765, 633, 785], "crop_hash": None, "feedback_at": 0.0}  # frame not kept
    log.append("s0", "camera_reading", unsaved)
    log.append("s0", "evaluation", {"source": "camera", "step": 2, "point": "f1", "tag": "f1_valve_pos", "camera": "optional",
                                    "readings": [unsaved], "feedback": [[1.0, 0.0]], "verdict_after": NDF, "with_camera_after": NDF,
                                    "findings": [{"rule_id": "LIVE-CAMERA", "rule_version": "2", "status": "PASS", "refs": ["f1_valve_pos"],
                                                  "path": [], "message": "f1_valve_pos: camera agrees with the feedback in 1 of 1 frames"}]})
    log.append("s0", "verdict", {"verdict": NDF, "reasons": []})
    log.append("s0", "session_stopped", {})
    start = next(e for e in bundle_events(b) if e["kind"] == "session_start")
    log.append("live", "session_start", start["payload"])  # still running: the live step mode
    log.append("live", "ready", {})
    log.close()
    PATHS.update(audit=tmp / "audit.sqlite", data=data)
    monkeypatch_module.setenv("MODEL_API_KEY", "fake-key-for-tests")  # pragma: allowlist secret
    monkeypatch_module.setenv("ZS_CREDITS", str(tmp / "credits.jsonl"))
    app = server.create_app(data, tmp / "audit.sqlite", tmp / "config", {}, opener=FakeModel(), poll_s=0.05, ui_dir=ROOT / "ui")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def run(page, base, session, text=Q):
    page.goto(f"{base}/ui/#/check?session={session}")
    page.fill("#check-text", text)
    page.click("#check-go")


def test_s8_walks_rows_in_order_zooms_and_ends_with_stop(page, check_server):
    run(page, check_server, "s8")
    page.wait_for_selector("#recorded-label .recorded")
    assert "muted" in page.text_content("#voice-note").lower()  # automated runs never speak aloud
    page.wait_for_selector("#camera-caption", timeout=30000)
    assert page.text_content("#camera-caption") == "camera: GRFICSv3 simulator, pre-existing"
    page.wait_for_selector("#final-line", timeout=60000)
    labels = page.eval_on_selector_all("#checklist tbody tr td:nth-child(2)", "els => els.map(e => e.textContent)")
    assert labels[:3] == ["PLC mode: manual_mode = 1", "valve f1: closed", "valve purge: closed"] and "Hold test" in labels
    marks = dict(zip(labels, page.eval_on_selector_all("#checklist td.mark", "els => els.map(e => e.dataset.mark)")))
    assert marks["valve f1: closed"] == "FAIL" and marks["Hold test"] == "none"  # never reached: not checked
    final = page.text_content("#final-line")
    assert final.startswith("STOP. Do not open the reactor. f1:") and "LIVE-VALVE" in final and "2 of 3 witnesses disagree" in final
    said = page.text_content("#spoken-line")  # one short sentence; the full text with the finding id stays on screen
    assert "STOP. Do not open the reactor. f1:" in said and "2 of 3 witnesses disagree." in said and "LIVE-VALVE" not in said
    page.wait_for_function("document.querySelector('#check-camera h2').textContent.includes('f1')")  # back on the deciding check
    page.click("button.why")
    page.wait_for_selector("#why-answer")
    assert page.text_content("#why-answer") == "f1 reads closed while its flow meter reads flow."
    assert page.locator("#check-explain a.cite").count() == 1
    assert page.locator("text=Accept and sign").count() == 0 and page.locator("#sign-open").count() == 0
    text = page.inner_text("body")
    assert wording.hits(text) == [], wording.hits(text)
    for c in page.eval_on_selector_all(".final, #checklist td", "els => els.flatMap(e => [getComputedStyle(e).backgroundColor, getComputedStyle(e).color])"):
        r, g, b = (int(x) for x in re.findall(r"\d+", c)[:3])
        assert not (g > r + 30 and g > b + 30), c


def test_no_frame_is_said_not_faked(page, check_server):
    run(page, check_server, "s0")
    page.wait_for_selector("#no-frame", timeout=60000)
    assert page.text_content("#no-frame") == "no camera frame for this check" and page.locator("#zoom").count() == 0


def test_s0_ends_with_the_exact_no_discrepancy_line(page, check_server):
    run(page, check_server, "s0")
    page.wait_for_selector("#final-line", timeout=60000)
    assert re.fullmatch(r"No discrepancy found in \d+ checks\. This is not a safety call; the issuer signs\.", page.text_content("#final-line"))
    assert "safe" not in page.inner_text("body").lower().replace("safety call", "")


def test_unclear_request_lists_the_confirmed_plans(page, check_server):
    run(page, check_server, "s8", "check the boiler")
    page.wait_for_selector("#check-unclear")
    assert page.text_content("#check-unclear").startswith("I can't tell which equipment you mean")
    assert page.locator("#plan-picker button[data-plan='plan-63e1519c']").count() == 1


def test_view_source_and_prompts_pass_the_never_say_check():
    files = [ROOT / "ui/check.js", ROOT / "src/zerostate/llm/prompts/explain_v1.md", ROOT / "src/zerostate/llm/prompts/resolve_request_v1.md"]
    assert wording.main([str(f) for f in files]) == 0


def test_job_camera_panel_reads_models_logged_as_a_dict(page, check_server):
    """Live camera evaluations log models as {locate, read}; the job screen's camera panel lists them."""
    page.goto(f"{check_server}/ui/#/job/s8")
    page.wait_for_function("document.querySelector('#camera') && document.querySelector('#camera').textContent.includes('models:')", timeout=30000)
    assert "models: sam-3.1, muse-spark-1.3" in page.text_content("#camera")


def test_live_step_mode_marks_only_after_the_read_back_and_stops_on_a_fail(page, check_server):
    """A running session: the worker marks a step by text after confirming the read-back (inbox gets one
    step_done, nothing else); rows tick as the engine logs findings; on a FAIL the view says STOP and stops
    prompting. The engine is played by appending to the throwaway audit log."""
    import sqlite3
    run(page, check_server, "live")
    page.wait_for_selector("#step-prompt")
    assert page.text_content("#step-prompt").startswith('Waiting: do step 1 (manual_mode = 1), then say "step 1 done"')
    page.fill("#worker-name", "Ana")
    page.fill("#step-cmd", "step one done")
    page.click("#step-send")
    page.wait_for_selector("#confirm-mark")
    assert "confirm" in page.text_content("#read-back-text").lower()
    db = PATHS["data"] / "inbox.sqlite"
    assert not db.exists()  # nothing is marked before the read-back is confirmed
    page.click("#confirm-mark")
    page.wait_for_function("document.querySelector('#step-prompt').textContent.includes('ZeroState is checking step 1')")
    rows = sqlite3.connect(db).execute("SELECT session, kind, payload_json FROM inbox").fetchall()
    assert [(r[0], r[1], json.loads(r[2])) for r in rows] == [("live", "step_done", {"k": 1, "by": "Ana"})]
    ok = {"rule_id": "LIVE-VALVE", "rule_version": "2", "status": "PASS", "refs": [], "path": [], "message": "commanded state, position and flow agree with the plan"}
    log = AuditLog(PATHS["audit"])
    log.append("live", "step_done", {"k": 1, "by": "Ana"})
    log.append("live", "evaluation", {"source": "step", "step": 1, "findings": [ok]})
    page.wait_for_selector('#checklist tr[data-row="1"] td.mark[data-mark="PASS"]', timeout=15000)
    page.wait_for_function("document.querySelector('#step-prompt').textContent.startsWith('Waiting: do step 2')", timeout=15000)
    log.append("live", "step_done", {"k": 2, "by": "Ana"})
    page.wait_for_selector('#verify-wait li[data-verify="2"] a[href="#/job/live"]', timeout=15000)
    assert "waiting for verification by a second person (console)" in page.text_content("#verify-wait")
    fail = {**ok, "status": "FAIL", "refs": ["f1_flow", "f1_valve_pos"],
            "message": "flow through a valve reading closed: f1_flow = 640.6 while f1_valve_pos = 0.0 % (passing valve or false feedback)"}
    log.append("live", "evaluation", {"source": "step", "step": 2, "findings": [fail]})
    log.append("live", "verdict", {"verdict": "BLOCKED", "reasons": [f"LIVE-VALVE: {fail['message']}"]})
    log.close()
    page.wait_for_selector("#final-line", timeout=30000)
    assert page.text_content("#final-line").startswith("STOP. Do not open the reactor. f1:")
    assert page.text_content("#step-prompt") == "No further steps are prompted." and page.locator("#step-form").count() == 0
    assert page.locator("button:has-text('Verify'), button:has-text('sign'), #sign-open").count() == 0
    assert len(sqlite3.connect(db).execute("SELECT * FROM inbox").fetchall()) == 1  # still only the one mark
    assert wording.hits(page.inner_text("body")) == []
