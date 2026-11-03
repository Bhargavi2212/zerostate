"""Camera channel, offline: fake model and frame functions, synthetic display images made with Pillow.
LIVE-CAMERA on its own track: a camera FAIL never reaches the data-only verdict."""

import io
from datetime import UTC, datetime

from checks.synth import PARAMS, PLAN, SPANS, steady
from PIL import Image, ImageDraw

from zerostate.audit.log import AuditLog
from zerostate.audit.replay import replay
from zerostate.camera import locate, read
from zerostate.camera.freeze import ahash, frozen
from zerostate.camera.track import CameraTrack, burst, load_display_map
from zerostate.checks.live import camera
from zerostate.llm.client import ModelUnavailable
from zerostate.models.signal import Quality, Signal
from zerostate.models.verdict import FindingStatus as S
from zerostate.models.verdict import Verdict
from zerostate.session import Session, status_from_events

SCALE, POLL = 10.0, 0.25
F1_BOX = [100, 100, 220, 150]


def frame(text: str = "100.0", size=(400, 300), seed_noise: int = 0) -> bytes:
    """A dark frame with one lit display at F1_BOX showing `text`; noisy like the frame service's frames."""
    img = Image.new("RGB", size, (40, 40, 40))
    d = ImageDraw.Draw(img)
    d.rectangle(F1_BOX, fill=(10, 10, 10))
    d.text((F1_BOX[0] + 10, F1_BOX[1] + 15), text, fill=(0, 255, 0), font_size=28)
    if seed_noise:
        noise = Image.effect_noise(size, 3).convert("RGB")
        img = Image.blend(img, noise, 0.02)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


def rd(t, value, readable=True, crop_hash=None, feedback_at=None):
    return {"t": t, "value": value, "readable": readable, "crop_hash": crop_hash, "feedback_at": feedback_at}


# ---- locate: region matching ------------------------------------------------------------------
def test_sam_boxes_match_display_regions_by_overlap():
    regions = {"f1": F1_BOX, "purge": [300, 200, 380, 240]}
    boxes = [{"x1": 105, "y1": 98, "x2": 225, "y2": 152, "c": 0.9},  # f1, slightly off
             {"x1": 10, "y1": 10, "x2": 40, "y2": 30, "c": 0.8}]  # some other display
    got = locate.match(boxes, regions, (400, 300))
    assert got["f1"] == (105, 98, 225, 152) and got["purge"] is None
    norm = [{"x1": 0.25, "y1": 1 / 3, "x2": 0.55, "y2": 0.5, "c": 0.9}]  # normalised boxes are scaled
    assert locate.match(norm, regions, (400, 300))["f1"] is not None
    assert locate.iou(F1_BOX, F1_BOX) == 1.0 and locate.iou(F1_BOX, [300, 0, 310, 10]) == 0.0


# ---- read: crop + unreadable handling ----------------------------------------------------------
def test_crop_pads_15_percent_and_enlarges_x3():
    img = Image.open(io.BytesIO(frame()))
    c = read.crop(img, (100, 100, 200, 140))
    assert c.size == (130 * 3, 52 * 3)


def test_read_never_turns_an_unclear_display_into_a_value():
    img = Image.open(io.BytesIO(frame()))

    def spark(value, readable):
        return lambda msgs, schema, purpose: schema(value=value, readable=readable)

    assert read.read_display(img, F1_BOX, spark(42.5, True)) == {"value": 42.5, "readable": True}
    assert read.read_display(img, F1_BOX, spark(42.5, False)) == {"value": None, "readable": False}
    assert read.read_display(img, F1_BOX, spark(None, True)) == {"value": None, "readable": False}


def test_burst_turns_model_and_fetch_failures_into_unreadable_readings():
    calls = {"fetch": 0}

    def fetch(view):
        calls["fetch"] += 1
        if calls["fetch"] == 2:
            raise OSError("connection refused")
        return frame(), 1000.0 + calls["fetch"]

    def sam(img, prompt, purpose):
        raise ModelUnavailable("budget reached")

    out = burst({"step": 2, "points": {"f1": ("default", F1_BOX)}}, fetch=fetch, sam=sam,
                spark=None, sleep=lambda s: None)
    rs = out[0]["readings"]
    assert out[0]["point"] == "f1" and len(rs) == 3 and not any(r["readable"] for r in rs)
    assert rs[1]["frame_sha256"] is None and "no frame" in rs[1]["note"]
    assert rs[0]["frame_sha256"] and "locate unavailable" in rs[0]["note"]


def test_burst_reads_each_located_display():
    sam = lambda img, prompt, purpose: [{"x1": 100, "y1": 100, "x2": 220, "y2": 150, "c": 0.9}]
    spark = lambda msgs, schema, purpose: schema(value=100.0, readable=True)
    out = burst({"step": 2, "points": {"f1": ("default", F1_BOX)}}, fetch=lambda v: (frame(), 5.0),
                sam=sam, spark=spark, sleep=lambda s: None)
    assert [r["value"] for r in out[0]["readings"]] == [100.0, 100.0, 100.0]


# ---- freeze detection ------------------------------------------------------------------------
def test_crop_hash_ignores_frame_noise_but_sees_a_new_value():
    def h(text, noise):
        return ahash(Image.open(io.BytesIO(frame(text, seed_noise=noise))).crop(F1_BOX))

    a, b, c = h("100.0", 0), h("100.0", 1), h("0.0", 1)
    from zerostate.camera.freeze import differ_pct
    assert differ_pct(a, b) <= PARAMS["camera_freeze_same_pct"] < differ_pct(a, c)
    assert ahash(Image.new("RGB", (50, 20), (30, 30, 30))) is None  # blank region: no judgement


def test_frozen_only_when_the_feedback_moved_beyond_the_lag():
    same = "f" * 64
    fb = [[0.0, 100.0], [20.0, 0.0]]  # valve closed at t=20
    prev = [{"t": 10.0, "crop_hash": same, "feedback_at": 100.0}]
    cur = [{"t": 30.0, "crop_hash": same}]
    assert frozen(prev + cur, fb, 5, 5, 5)
    assert not frozen(prev + [{"t": 23.0, "crop_hash": same}], fb, 5, 5, 5)  # still inside the lag
    assert not frozen(prev + [{"t": 30.0, "crop_hash": "0" * 64}], fb, 5, 5, 5)  # display changed
    assert not frozen([{"t": 10.0, "crop_hash": same, "feedback_at": 0.0}, *cur], fb, 5, 5, 5)  # feedback did not move


# ---- LIVE-CAMERA ----------------------------------------------------------------------------
FB = [[0.0, 100.0], [9.0, 100.0], [10.0, 0.0], [12.0, 0.0], [16.0, 0.0]]  # f1 closed at t=10


def test_live_camera_pass_within_the_lag_window():
    # at t=12 the display may still show 100 (lag 5 s); at t=16 it shows 0
    f = camera.check([rd(12.0, 100.0), rd(14.0, 100.0), rd(16.0, 0.0)], FB, PARAMS, tag="f1_valve_pos")
    assert f.status == S.PASS and f.rule_id == "LIVE-CAMERA"


def test_live_camera_fail_names_both_values():
    f = camera.check([rd(16.0, 50.0), rd(17.0, 50.0)], FB + [[17.0, 0.0]], PARAMS, tag="f1_valve_pos")
    assert f.status == S.FAIL and f.message == "camera shows 50 % while the instrument says 0.0 % (f1_valve_pos)"


def test_live_camera_unknown_with_fewer_than_two_readable_frames():
    f = camera.check([rd(16.0, 0.0), rd(17.0, None, False), rd(18.0, None, False)], FB, PARAMS, tag="f1_valve_pos")
    assert f.status == S.UNKNOWN
    assert camera.check([rd(16.0, 0.0), rd(17.0, 0.0)], [], PARAMS).status == S.UNKNOWN  # no feedback


def test_live_camera_fails_a_frozen_display():
    same = "f" * 64
    prev = [{"t": 5.0, "crop_hash": same, "feedback_at": 100.0}]
    f = camera.check([rd(16.0, 0.0, crop_hash=same), rd(18.0, 0.0, crop_hash=same)], FB, PARAMS, prev, "f1_valve_pos")
    assert f.status == S.FAIL and "display frozen" in f.message


def test_optional_unknown_is_ignored_required_unknown_escalates():
    assert camera.contribution(S.UNKNOWN, "optional") is None
    assert camera.contribution(S.UNKNOWN, "required") == Verdict.ESCALATED
    assert camera.contribution(S.FAIL, "optional") == Verdict.BLOCKED
    assert camera.contribution(S.PASS, "required") is None  # a camera never yields a pass


# ---- the with-camera track beside a session ---------------------------------------------------
class Rig:
    def __init__(self, tmp_path, mode, dmap=None):
        self.plan = PLAN.model_copy(update={"camera": mode})
        self.log = AuditLog(tmp_path / "audit.sqlite")
        self.s = Session("s1", self.plan, self.plan.content_hash(), PARAMS, SCALE, SPANS, self.log, now=0.0)
        dmap = dmap or {"f1": ("default", F1_BOX), "purge": ("default", [300, 200, 380, 240])}
        self.cam = CameraTrack("s1", self.plan, PARAMS, self.log, dmap, SCALE)
        self.t, self.jobs = 0.0, []

    def run(self, wall_s, inbox=()):
        inbox = list(inbox)
        for _ in range(int(wall_s / POLL)):
            self.t += POLL
            sig = {k: Signal(tag=k, value=v, raw=0, quality=Quality.GOOD, source_ts=None, recv_ts=datetime.now(UTC))
                   for k, v in steady(pressure=2700.0).items()}
            self.s.tick(self.t, sig, inbox)
            inbox = []
            self.cam.observe(self.t, sig)
            self.jobs += self.cam.due(self.t, self.s.marks, self.s.steps, self.s.verdict)

    def status(self):
        return status_from_events(self.log.events("s1"))

    def to_step_2(self):
        self.run(2)
        self.run(POLL, [{"kind": "step_done", "k": 1, "by": "op"}])
        self.run(3)
        self.run(POLL, [{"kind": "step_done", "k": 2, "by": "op"}])
        self.run(8)  # settle (60 process-s = 6 s wall) has passed: a capture was started

    def readings(self, values):
        t = self.t
        return [rd(t - 4 + 2 * i, v, v is not None) | {"frame_sha256": "ab" * 32} for i, v in enumerate(values)]


def test_camera_fail_blocks_only_the_with_camera_track_and_replays(tmp_path):
    r = Rig(tmp_path, "optional")
    r.to_step_2()
    assert [j["step"] for j in r.jobs] == [2] and r.status()["camera_pending"] == 2
    r.cam.record({"step": 2, "point": "f1", "readings": r.readings([100.0, 100.0, 100.0])}, r.s.verdict)  # feedback is 0
    r.cam.record({"step": 2, "point": "purge", "readings": r.readings([0.0, 0.0, 0.0])}, r.s.verdict)
    r.s.camera_verdict = r.cam.verdict
    st = r.status()
    assert st["verdict"] is None and st["steps"][2] == "PASS"  # data-only track untouched by the camera FAIL
    assert st["verdict_with_camera"] == "BLOCKED" and st["camera_pending"] == 0
    assert "camera shows 100 % while the instrument says 0.0 % (f1_valve_pos)" in st["stamp_with_camera"]["reasons"][0]
    assert st["stamp_with_camera"]["models"] == {"locate": "sam-3.1", "read": "muse-spark-1.3"}
    assert st["stamp_with_camera"]["rules"]["LIVE-CAMERA"] == camera.RULE_VERSION
    assert {e["kind"] for e in r.log.events("s1")} >= {"camera_capture", "camera_reading"}
    assert not any("frame" in k and k != "frame_sha256" for e in r.log.events("s1") if e["kind"] == "camera_reading"
                   for k in e["payload"])  # a hash, never the frame
    assert replay(r.log, "s1", PARAMS) == []
    r.run(POLL, [{"kind": "sign", "by": "receiver-a", "role": "receiver"}])
    sig = r.status()["signature"]
    assert sig["verdict_at_signing"] is None and sig["verdict_with_camera_at_signing"] == "BLOCKED"


def test_unreadable_camera_ignored_when_optional_escalates_when_required(tmp_path):
    for mode, want in (("optional", None), ("required", "ESCALATED")):
        (tmp_path / mode).mkdir()
        r = Rig(tmp_path / mode, mode)
        r.to_step_2()
        for p in ("f1", "purge"):
            r.cam.record({"step": 2, "point": p, "readings": r.readings([None, None, None])}, r.s.verdict)
        st = r.status()
        assert st["verdict"] is None and st["verdict_with_camera"] == want
        assert replay(r.log, "s1", PARAMS) == []


def test_tampered_camera_reading_breaks_replay(tmp_path):
    r = Rig(tmp_path, "optional")
    r.to_step_2()
    r.cam.record({"step": 2, "point": "f1", "readings": r.readings([0.0, 0.0, 0.0])}, r.s.verdict)
    log2 = AuditLog(tmp_path / "copy.sqlite")
    for e in r.log.events("s1"):
        p = e["payload"]
        if e["kind"] == "evaluation" and p["source"] == "camera":
            p = p | {"readings": [x | {"value": 100.0} for x in p["readings"]]}
        log2.append("s1", e["kind"], p)
    assert any("camera" in m for m in replay(log2, "s1", PARAMS))


def test_no_camera_in_the_plan_means_equal_tracks(tmp_path):
    log = AuditLog(tmp_path / "a.sqlite")
    Session("s1", PLAN, PLAN.content_hash(), PARAMS, SCALE, SPANS, log, now=0.0)
    st = status_from_events(log.events("s1"))
    assert st["verdict_with_camera"] == st["verdict"] and st["camera_pending"] == 0


def test_display_map_file_loads():
    from pathlib import Path

    m = load_display_map(Path(__file__).parents[1] / "plants" / "frame_service" / "display_map.yaml")
    assert m["f1"][0] == "default" and len(m["f1"][1]) == 4


def test_read_accuracy_scoring():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("read_accuracy", Path(__file__).parents[1] / "eval" / "read_accuracy.py")
    ra = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ra)
    out = {"a": {"f1": {"value": 50.5, "readable": True}, "error": "x"}, "b": {"f1": {"value": 47.0, "readable": True}},
           "c": {"f1": {"value": None, "readable": False}}}
    rep = ra.score(out, {"a": {"f1": 50.0}, "b": {"f1": 50.0}, "c": {"f1": 10.0}})
    f1 = rep["per_valve"]["f1"]
    assert (f1["n"], f1["exact_1pct"], f1["within_5pct"], f1["unreadable"]) == (3, 1, 2, 1)
    assert ra.label({"truth": {"measured": {"f1_valve_pos": 12.5}}}, "f1") == 12.5

def test_cli_camera_track_wiring(tmp_path, monkeypatch):
    from zerostate import cli

    monkeypatch.delenv("ZS_FRAMES_URL", raising=False)
    for mode, want in ((None, None), ("optional", None), ("required", "ESCALATED")):
        log = AuditLog(tmp_path / f"{mode}.sqlite")
        plan = PLAN.model_copy(update={"camera": mode})
        s = Session("s1", plan, plan.content_hash(), PARAMS, SCALE, SPANS, log, now=0.0)
        assert cli.camera_track(s, plan, log, SCALE, None) == (None, None, None)
        st = status_from_events(log.events("s1"))
        assert st["verdict"] is None and st["verdict_with_camera"] == want and st["camera_pending"] == 0
        assert sum(e["kind"] == "evaluation" for e in log.events("s1")) == (0 if mode is None else 1)
        assert replay(log, "s1", PARAMS) == []

def test_required_camera_escalates_a_valve_without_a_mapped_display(tmp_path):
    r = Rig(tmp_path, "required", dmap={"f1": ("default", F1_BOX)})  # purge has no display in view
    r.to_step_2()
    st = r.status()
    assert st["camera_pending"] == 1 and st["verdict_with_camera"] == "ESCALATED" and st["verdict"] is None
    assert "no display mapped for purge" in str([e["payload"].get("note") for e in r.log.events("s1")])
    assert replay(r.log, "s1", PARAMS) == []