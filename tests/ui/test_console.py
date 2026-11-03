"""P3-3 operator console, in a real browser against the fixture server (tests/ui/fake_api.py) and a
throwaway data dir. Every screen renders a recorded session; the verdict banner is never green; runner
names read "test harness"; Close — not accepted records not_accepted; unclear cells block Confirm;
dialogs are submitted only as playwright-test in the throwaway dir."""

import json
import re
from pathlib import Path

import pytest
from fake_api import BLOCKED_EP, TEST_NAME, TRANSCRIPT

pytestmark = pytest.mark.ui

NDF_TEXT = "NO DISCREPANCY FOUND — awaiting sign-off"
HEADER = "work_order,equipment,tag,required_state,apply_seq,isolation_type,lock_id,vent_tag,proving_tag,proves\n"
ROWS_NO_XV204 = ["WO-1,F-210,XV-201,closed,1,proved,A-01,VV-213,BV-202,XV-201;XV-203",
                 "WO-1,F-210,XV-203,closed,2,proved,A-02,VV-213,,",
                 "WO-1,F-210,BV-202,open,3,,,VV-213,,"]


def open_job(page, ui_server, sid):
    base, _ = ui_server
    page.goto(f"{base}/ui/#/job/{sid}")
    page.wait_for_selector("#verdict-banner")
    page.wait_for_function("document.querySelector('#stream-state').textContent.includes('ended') "
                           "|| document.querySelector('#stream-state').textContent.includes('closed')")


def inbox(data: Path) -> list[dict]:
    p = data / "inbox.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def assert_never_green(page):
    """Every verdict element's computed colours: green may never dominate (ISA-101 + the spec)."""
    colours = page.eval_on_selector_all(".track, .badge, .banner", """els => els.flatMap(e => {
        const s = getComputedStyle(e);
        return [s.backgroundColor, s.color, s.borderTopColor];
    })""")
    assert colours
    for c in colours:
        r, g, b = (int(x) for x in re.findall(r"\d+", c)[:3])
        assert not (g > r + 30 and g > b + 30), c


def test_session_list(page, ui_server):
    base, _ = ui_server
    page.goto(f"{base}/ui/#/")
    rows = page.locator("#sessions tbody tr")
    assert rows.count() == 3
    assert "BLOCKED" in page.locator(f"tr[data-session='{BLOCKED_EP}']").inner_text()
    assert_never_green(page)


def test_blocked_job_renders_recorded_session(page, ui_server):
    open_job(page, ui_server, BLOCKED_EP)
    data_track = page.locator("[data-track='Data-only track']").inner_text()
    assert "BLOCKED: LIVE-HOLD: pressure rose 29.9 kPa" in data_track
    assert "BLOCKED" in page.locator("[data-track='With-camera track']").inner_text()
    strip = page.locator("#assumptions").inner_text()
    assert "positive isolation upstream assumed" in strip and "plan check overridden" in strip
    body = page.locator("body").inner_text()
    assert "test harness" in page.locator("#steps-table").inner_text()
    assert "eval-operator" not in body and "eval-runner" not in body
    assert page.locator("tr[data-step='7'] td").nth(6).inner_text().endswith("FAIL")
    page.locator("rect.band-hold").first.wait_for()  # charts redraw just after the stream's evaluations
    assert page.locator(".chart").count() == 3
    assert page.locator("rect.band-hold").count() >= 1 and page.locator("rect.band-vent").count() >= 1
    assert page.locator("svg.plant g[data-node='f1']").count() == 1
    assert "idealised camera (renders the simulator's true state)" in page.locator("#camera").inner_text()
    assert page.locator("#findings-table tr.f-FAIL").count() >= 1
    assert_never_green(page)


def test_close_not_accepted_records_not_accepted(page, ui_server):
    _, data = ui_server
    open_job(page, ui_server, BLOCKED_EP)
    button = page.locator("#sign-open")
    assert button.inner_text() == "Close — not accepted…"
    button.click()
    dlg = page.locator("#name-dialog")
    assert "NOT accepted" in dlg.inner_text() and "Accept and sign" not in dlg.inner_text()
    page.fill("#dlg-name", TEST_NAME)
    page.click("#dlg-submit")
    page.wait_for_selector("#action-msg")
    assert data.resolve() != Path("/data").resolve()
    row = [r for r in inbox(data) if r["session"] == BLOCKED_EP and r["kind"] == "sign"][-1]
    assert row["outcome"] == "not_accepted" and row["by"] == TEST_NAME


def test_accept_and_sign_only_on_no_discrepancy(page, ui_server):
    base, data = ui_server
    page.goto(f"{base}/ui/#/")
    sid = page.locator("#sessions tbody tr").filter(has_text="NO DISCREPANCY").first.get_attribute("data-session")
    open_job(page, ui_server, sid)
    assert NDF_TEXT in page.locator("[data-track='Data-only track']").inner_text()
    assert NDF_TEXT in page.locator("[data-track='With-camera track']").inner_text()
    assert_never_green(page)
    page.click("#sign-open")
    page.fill("#dlg-name", TEST_NAME)
    page.click("#dlg-submit")
    page.wait_for_selector("#action-msg")
    row = [r for r in inbox(data) if r["session"] == sid and r["kind"] == "sign"][-1]
    assert row["outcome"] == "accepted" and row["by"] == TEST_NAME


def test_live_job_mark_verify_and_camera(page, ui_server):
    _, data = ui_server
    open_job(page, ui_server, "ui-live")
    assert "Evaluating…" in page.locator("#verdict-banner").inner_text()
    assert page.locator("#sign-open").inner_text() == "Close — not accepted…"
    assert "test harness" in page.locator("tr[data-step='1'] .verified-by").inner_text()
    page.click("tr[data-step='3'] [data-action='done']")
    page.fill("#dlg-name", TEST_NAME)
    page.click("#dlg-submit")
    page.wait_for_selector("#action-msg")
    assert {"session": "ui-live", "kind": "step_done", "k": 3, "by": TEST_NAME} in inbox(data)
    # verify needs a different entered name from the marker
    page.click("tr[data-step='2'] [data-action='verify']")
    page.fill("#dlg-name", "eval-operator")
    page.click("#dlg-submit")
    assert "different name" in page.locator("#dlg-msg").inner_text()
    page.fill("#dlg-name", TEST_NAME)
    page.click("#dlg-submit")
    page.wait_for_function("document.querySelector('#action-msg').textContent.includes('Queued')")
    assert {"session": "ui-live", "kind": "step_verify", "k": 2, "by": TEST_NAME} in inbox(data)
    cam = page.locator("#camera")
    cam.locator("img.frame-img").wait_for()
    assert cam.locator("svg.sam-box rect").count() == 1
    text = cam.inner_text()
    assert "idealised camera (renders the simulator's true state)" in text
    assert "reading: 0.0 % open" in text and "feedback at read: 0.0 % open" in text


def test_explain_cites_findings_as_links(page, ui_server):
    open_job(page, ui_server, BLOCKED_EP)
    page.locator(".explain-btn").first.click()
    cite = page.locator("#explain-answer a.cite").first
    cite.wait_for()
    fid = cite.inner_text()
    assert re.fullmatch(r"\d+:[A-Z-]+", fid) and cite.get_attribute("href") == f"#finding-{fid}"
    assert page.locator(f"[id='finding-{fid}']").count() == 1
    cite.click()
    assert f"#/job/{BLOCKED_EP}" in page.url  # the link scrolls; it does not leave the job


def test_unclear_cell_blocks_confirm_then_confirm(page, ui_server):
    base, data = ui_server
    page.goto(f"{base}/ui/#/new")
    page.fill("#text-in", TRANSCRIPT)
    page.click("#import")
    page.wait_for_selector("#points")
    assert page.locator("#confirm-open").is_disabled()
    assert "isolation_type is unclear" in page.locator("#confirm-box").inner_text()
    assert page.locator("#points .unclear").count() == 1
    assert page.locator("[data-default='hold_minutes']").inner_text() == "plant default: 10"
    page.locator("tr[data-point='1'] select[name='isolation_type']").select_option("proved")
    page.wait_for_function("!document.querySelector('#confirm-open').disabled")
    assert page.locator("svg.plant g.work[data-node='F-210']").count() == 1
    page.click("#confirm-open")
    submit = page.locator("#confirm-submit")
    page.fill("#confirm-name", TEST_NAME)
    assert submit.is_disabled()  # the review box is not ticked yet
    page.check("#confirm-reviewed")
    submit.click()
    page.wait_for_selector("#confirmed-record")
    assert data.resolve() != Path("/data").resolve()
    assert any(json.loads(p.read_text())["confirmed"][-1]["by"] == TEST_NAME for p in (data / "plans").glob("*.json"))


def test_csv_open_path_drawn_red(page, ui_server, tmp_path):
    base, _ = ui_server
    csv = tmp_path / "export.csv"
    csv.write_text(HEADER + "\n".join(ROWS_NO_XV204) + "\n", encoding="utf-8")
    page.goto(f"{base}/ui/#/new")
    page.click("[data-tab='csv']")
    page.set_input_files("#csv-in", str(csv))
    page.click("#import")
    page.wait_for_selector("#plan-check li.f-FAIL")
    assert page.locator("svg.plant line.open-path").count() >= 1
    assert "Open path:" in page.locator(".plantwrap").inner_text()


def test_upload_shows_photo_and_transcript_side_by_side(page, ui_server, tmp_path):
    from PIL import Image

    base, _ = ui_server
    png = tmp_path / "sheet.png"
    Image.new("RGB", (60, 40), (250, 250, 250)).save(png)
    page.goto(f"{base}/ui/#/new")
    page.click("[data-tab='image']")
    page.set_input_files("#image-in", str(png))
    page.click("#import")
    side = page.locator("#photo-transcript")
    side.wait_for()
    assert side.locator("img.photo").count() == 1
    assert TRANSCRIPT in side.inner_text()


@pytest.mark.skip(reason="waits for zerostate.wording")
def test_never_say_over_rendered_text(page, ui_server):
    pass
