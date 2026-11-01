"""Session lifecycle and verdict policy over time (fake clock, synthetic P1 signals at 4 Hz, x10)."""

from datetime import UTC, datetime

import pytest
from checks.synth import PARAMS, PLAN, SPANS, steady, vent

from zerostate.audit.log import AuditLog
from zerostate.audit.replay import replay
from zerostate.models.signal import Quality, Signal
from zerostate.session import PlanHashMismatch, Session, status_from_events

SCALE, POLL = 10.0, 0.25


class Driver:
    def __init__(self, tmp_path, quality=lambda t, tag: "GOOD"):
        self.log = AuditLog(tmp_path / "audit.sqlite")
        self.t, self.quality, self.fn, self.fn_t0 = 0.0, quality, (lambda ps: steady(pressure=2700.0)), 0.0
        self.s = Session("s1", PLAN, PLAN.content_hash(), PARAMS, SCALE, SPANS, self.log, now=0.0)

    def run(self, wall_s, inbox=()):
        inbox = list(inbox)
        for _ in range(int(wall_s / POLL)):
            self.t += POLL
            vals = self.fn((self.t - self.fn_t0) * SCALE)
            sig = {k: Signal(tag=k, value=v, raw=0, quality=Quality(self.quality(self.t, k)), source_ts=None,
                             recv_ts=datetime.now(UTC)) for k, v in vals.items()}
            self.s.tick(self.t, sig, inbox)
            inbox = []

    def mark(self, k, fn=None):
        if fn is not None:
            self.fn, self.fn_t0 = fn, self.t
        self.run(POLL, [{"kind": "step_done", "k": k, "by": "op"}])

    def status(self):
        return status_from_events(self.log.events("s1"))


def until_evaluated(d, k, limit_wall_s=120):
    for _ in range(int(limit_wall_s / POLL)):
        if d.status()["steps"].get(k) not in (None, "pending"):
            return
        d.run(POLL)
    raise AssertionError(f"step {k} never evaluated")


def clean_run(d):
    d.run(2)
    for k in (1, 2, 3, 4):
        d.mark(k, lambda ps: steady(pressure=2700.0))
        until_evaluated(d, k)
    d.mark(5, vent)
    until_evaluated(d, 5)
    d.run(25)  # like the runner: keep venting until the vent target (~366 process-s from 2700 kPa)
    d.mark(6, lambda ps: steady(pressure=100.0))
    until_evaluated(d, 6)
    d.mark(7, lambda ps: steady(pressure=100.0))
    until_evaluated(d, 7)


def test_wrong_plan_hash_refused(tmp_path):
    with pytest.raises(PlanHashMismatch):
        Session("s1", PLAN, "0" * 64, PARAMS, SCALE, SPANS, AuditLog(tmp_path / "a.sqlite"), now=0.0)


def test_clean_session_reaches_no_discrepancy_and_replays(tmp_path):
    d = Driver(tmp_path)
    clean_run(d)
    st = d.status()
    assert st["verdict"] == "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"
    assert all(v == "PASS" for v in st["steps"].values()) and 8 in st["steps"]
    assert st["stamp"]["assumptions"] == ["positive isolation upstream assumed"]
    assert replay(d.log, "s1", PARAMS) == []
    assert d.log.verify() == (True, None)


def test_warm_in_timeout_escalates(tmp_path):
    d = Driver(tmp_path, quality=lambda t, tag: "STALE" if tag == "pressure" else "GOOD")
    d.run(31)
    st = d.status()
    assert st["state"] == "warming_in" and st["verdict"] == "ESCALATED"
    assert "instruments not verified live" in st["stamp"]["reasons"][0]


def test_marks_refused_before_ready_and_out_of_order(tmp_path):
    d = Driver(tmp_path, quality=lambda t, tag: "UNKNOWN" if t < 1 else "GOOD")
    d.mark(1)
    assert d.status()["refused"][0]["reason"].startswith("session is warming_in")
    d.run(2)
    d.mark(2)
    assert "next step is 1" in d.status()["refused"][-1]["reason"]
    d.mark(1)
    d.mark(2)  # step 1 still pending
    assert d.status()["refused"][-1]["reason"] == "previous step not evaluated yet"
    assert d.status()["verdict"] is None  # pending is not a verdict


def test_monitor_ignores_a_valve_still_settling_but_blocks_after(tmp_path):
    d = Driver(tmp_path)
    d.run(2)
    d.mark(1, lambda ps: steady(pressure=2700.0))
    until_evaluated(d, 1)
    # f1 still flowing for the first 30 process-s after its mark (inside its 60 s settle)
    d.mark(2, lambda ps: steady(pressure=2700.0, f1_flow=640.0) if ps < 30 else steady(pressure=2700.0))
    until_evaluated(d, 2)
    assert d.status()["verdict"] is None
    d.fn, d.fn_t0 = (lambda ps: steady(pressure=2700.0, f1_flow=640.0)), d.t  # now it passes flow while reading closed
    d.run(3)
    assert d.status()["verdict"] == "BLOCKED"


def test_unknown_grace_then_escalate(tmp_path):
    d = Driver(tmp_path)
    d.run(2)
    d.mark(1, lambda ps: steady(pressure=2700.0))
    until_evaluated(d, 1)
    d.mark(2)
    until_evaluated(d, 2)
    t_bad = d.t
    d.quality = lambda t, tag: "STALE" if tag == "pressure" and t > t_bad else "GOOD"
    d.run(6)
    assert d.status()["verdict"] is None  # within the 10 s grace
    d.run(8)
    assert d.status()["verdict"] == "ESCALATED"
    assert replay(d.log, "s1", PARAMS) == []


def test_verdict_never_improves_and_sign_closes(tmp_path):
    d = Driver(tmp_path)
    d.run(2)
    d.mark(1, lambda ps: steady(pressure=2700.0, manual_mode=0.0))  # S6-like: manual mode never set
    until_evaluated(d, 1)
    assert d.status()["verdict"] == "BLOCKED"
    d.fn = lambda ps: steady(pressure=2700.0)
    d.run(5)
    assert d.status()["verdict"] == "BLOCKED"
    d.run(POLL, [{"kind": "sign", "by": "receiver-a", "role": "receiver"}])
    st = d.status()
    assert st["state"] == "closed" and st["signature"]["verdict_at_signing"] == "BLOCKED"


def test_stop_leaves_the_session_unsigned(tmp_path):
    d = Driver(tmp_path)
    d.run(2, [{"kind": "stop", "by": "eval-runner"}])
    st = d.status()
    assert st["state"] == "stopped" and "signature" not in st


def test_monitor_catches_a_dropout_jump_with_the_rate_test(tmp_path):
    # floor switched off so only the rate test can see it: a dropout during the hold-up of steps 2-4
    d = Driver(tmp_path)
    d.s.params = PARAMS | {"pressure_min_kpa": 0}
    d.run(2)
    d.mark(1, lambda ps: steady(pressure=2700.0))
    until_evaluated(d, 1)
    d.mark(2)
    until_evaluated(d, 2)
    d.fn, d.fn_t0 = (lambda ps: steady(pressure=0.0 if ps < 5 else 2700.0)), d.t
    d.run(4)
    st = d.status()
    assert st["verdict"] == "BLOCKED" and "faster than the process" in st["stamp"]["reasons"][0]


def test_buffer_stays_bounded_in_a_long_session(tmp_path):
    d = Driver(tmp_path)
    clean_run(d)
    d.run(300)  # five more minutes of monitoring after NO_DISCREPANCY (a session open for a shift)
    keep_wall = PARAMS["rate_window_process_s"] / SCALE + PARAMS["monitor_period_wall_s"] + POLL
    assert max(len(rows) for rows in d.s.buffer.values()) <= keep_wall / POLL + 2
    assert d.status()["verdict"] == "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"


def test_monitor_crash_escalates_and_still_replays(tmp_path):
    d = Driver(tmp_path)
    clean_run(d)
    d.s.fail("OperationalError: database is locked")
    st = d.status()
    assert st["verdict"] == "ESCALATED" and st["stamp"]["reasons"] == ["monitor stopped: OperationalError: database is locked"]
    assert replay(d.log, "s1", PARAMS) == []
