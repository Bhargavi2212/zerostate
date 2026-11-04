"""Session lifecycle and verdict policy over time (fake clock, synthetic P1 signals at 4 Hz, x10)."""

from datetime import UTC, datetime

import pytest
from checks.synth import HOLD, PARAMS, PLAN, SPANS, VENT, VENT_CLOSE, steady, vent

from zerostate.audit.log import AuditLog
from zerostate.audit.replay import replay
from zerostate.models.signal import Quality, Signal
from zerostate.session import PlanHashMismatch, Session, status_from_events

SCALE, POLL = 10.0, 0.25


class Driver:
    def __init__(self, tmp_path, quality=lambda t, tag: "GOOD", **session_kw):
        self.log = AuditLog(tmp_path / "audit.sqlite")
        self.t, self.quality, self.fn, self.fn_t0 = 0.0, quality, (lambda ps: steady(pressure=2700.0)), 0.0
        self.s = Session("s1", PLAN, PLAN.content_hash(), PARAMS, SCALE, SPANS, self.log, now=0.0, **session_kw)

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

    def verify(self, k, by="op2"):
        self.run(POLL, [{"kind": "step_verify", "k": k, "by": by}])

    def status(self):
        return status_from_events(self.log.events("s1"))


def until_evaluated(d, k, limit_wall_s=120):
    for _ in range(int(limit_wall_s / POLL)):
        if d.status()["steps"].get(k) not in (None, "pending"):
            return
        d.run(POLL)
    raise AssertionError(f"step {k} never evaluated")


    def verify(self, k, by="op2"):
        self.run(POLL, [{"kind": "step_verify", "k": k, "by": by}])


def clean_run(d, verifier="op2", skip_verify=(), reopen_f1=None):
    """reopen_f1: None, or whether the inch-and-test of f1 after the isolation is verified again."""
    d.run(2)
    for k in range(1, VENT):  # mode, then close f1, f2, product, purge
        d.mark(k, lambda ps: steady(pressure=2700.0))
        until_evaluated(d, k)
        if PLAN.steps[k - 1].kind == "isolate" and k not in skip_verify:
            d.verify(k, verifier)  # a second person checks each isolate step (PROC-INDEPENDENCE)
    if reopen_f1 is not None:
        d.run(POLL, [{"kind": "step_reopen", "k": 2, "by": "op", "reason": "inch and test f1"}])
        d.fn, d.fn_t0 = (lambda ps: steady(pressure=2700.0, f1_valve_pos=20.0, f1_cmd=20.0, f1_flow=200.0)), d.t
        d.run(5)
        st = d.status()
        assert 2 not in st["steps"] and st["verdict"] is None  # f1 open on purpose: pending, not monitored
        d.mark(2, lambda ps: steady(pressure=2700.0))  # closed again
        until_evaluated(d, 2)
        if reopen_f1:
            d.verify(2, verifier)
    d.mark(VENT, vent)
    until_evaluated(d, VENT)
    d.run(25)  # like the runner: keep venting until the vent target (~366 process-s from 2700 kPa)
    d.mark(VENT_CLOSE, lambda ps: steady(pressure=100.0))
    until_evaluated(d, VENT_CLOSE)
    d.mark(HOLD, lambda ps: steady(pressure=100.0))
    until_evaluated(d, HOLD)


def test_wrong_plan_hash_refused(tmp_path):
    with pytest.raises(PlanHashMismatch):
        Session("s1", PLAN, "0" * 64, PARAMS, SCALE, SPANS, AuditLog(tmp_path / "a.sqlite"), now=0.0)


def test_clean_session_reaches_no_discrepancy_and_replays(tmp_path):
    d = Driver(tmp_path)
    clean_run(d)
    st = d.status()
    assert st["verdict"] == "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"
    assert all(v == "PASS" for v in st["steps"].values()) and len(PLAN.steps) in st["steps"]
    assert st["stamp"]["assumptions"] == ["positive isolation upstream assumed"]
    assert replay(d.log, "s1", PARAMS) == []
    assert d.log.verify() == (True, None)


def test_installer_verifying_own_step_blocks(tmp_path):
    d = Driver(tmp_path)
    d.run(2)
    d.verify(1)  # nothing marked yet: refused and logged
    assert d.status()["refused"][-1] == {"k": 1, "by": "op2", "reason": "step 1 not marked done yet", "action": "verify"}
    for k in (1, 2):
        d.mark(k)
        until_evaluated(d, k)
    d.verify(2, by="op")  # the one who marked it
    st = d.status()
    assert st["verdict"] == "BLOCKED" and st["steps"][2] == "FAIL"
    assert st["stamp"]["reasons"] == ["PROC-INDEPENDENCE: step 2 verified by op, the person who marked it done"]
    assert replay(d.log, "s1", PARAMS) == []


def test_missing_verify_at_final_escalates_instead_of_no_discrepancy(tmp_path):
    d = Driver(tmp_path)
    clean_run(d, skip_verify=(3,))
    st = d.status()
    assert st["verdict"] == "ESCALATED"
    assert st["stamp"]["reasons"] == ["PROC-INDEPENDENCE: isolate steps not verified by a second person: 3"]
    assert "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF" not in [e["payload"]["verdict"] for e in d.log.events("s1") if e["kind"] == "verdict"]
    assert replay(d.log, "s1", PARAMS) == []


def test_reopen_done_again_and_verified_again_completes_and_replays(tmp_path):
    d = Driver(tmp_path)
    clean_run(d, reopen_f1=True)
    assert d.status()["verdict"] == "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"
    assert [e["payload"]["pending"] for e in d.log.events("s1") if e["kind"] == "step_reopen"] == [[2]]
    assert replay(d.log, "s1", PARAMS) == []


def test_reopen_not_verified_again_never_reaches_no_discrepancy(tmp_path):
    d = Driver(tmp_path)
    clean_run(d, reopen_f1=False)
    st = d.status()
    assert st["verdict"] == "BLOCKED"
    assert st["stamp"]["reasons"] == ["PROC-RESET: step 2 not verified again by a second person after step 2 was reopened"]
    assert "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF" not in [e["payload"]["verdict"] for e in d.log.events("s1") if e["kind"] == "verdict"]
    assert replay(d.log, "s1", PARAMS) == []


def test_reopen_refused_before_its_mark_and_after_a_verdict(tmp_path):
    d = Driver(tmp_path)
    d.run(2)
    d.run(POLL, [{"kind": "step_reopen", "k": 2, "by": "op", "reason": "test"}])
    assert d.status()["refused"][-1]["reason"] == "step 2 not marked done yet"
    clean_run(d)
    d.run(POLL, [{"kind": "step_reopen", "k": 2, "by": "op", "reason": "test"}])
    assert d.status()["refused"][-1]["reason"].startswith("verdict is already NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF")


def test_warm_in_timeout_escalates(tmp_path):
    d = Driver(tmp_path, quality=lambda t, tag: "STALE" if tag == "pressure" else "GOOD")
    d.run(31)
    st = d.status()
    assert st["state"] == "warming_in" and st["verdict"] == "ESCALATED"
    assert "instruments not verified live" in st["stamp"]["reasons"][0]


def test_mark_before_ready_refused_and_pending_is_not_a_verdict(tmp_path):
    d = Driver(tmp_path, quality=lambda t, tag: "UNKNOWN" if t < 1 else "GOOD")
    d.mark(1)
    assert d.status()["refused"][0]["reason"].startswith("session is warming_in")
    d.run(2)
    d.mark(1)
    d.mark(1)  # a repeated mark is refused, not a sequence fault
    assert d.status()["refused"][-1]["reason"] == "step 1 already marked"
    assert d.status()["verdict"] is None  # pending is not a verdict
    assert replay(d.log, "s1", PARAMS) == []


def test_mark_while_previous_step_pending_blocks(tmp_path):
    d = Driver(tmp_path)
    d.run(2)
    d.mark(1)
    d.mark(2)  # step 1 still pending
    st = d.status()
    assert st["verdict"] == "BLOCKED" and st["steps"][2] == "FAIL"
    assert st["stamp"]["reasons"] == ["PROC-SEQUENCE: step 2 marked before step 1 was verified"]
    assert 2 not in d.s.marks  # logged and judged, never evaluated as a step


def test_skipped_step_blocks_and_replays(tmp_path):
    d = Driver(tmp_path)
    d.run(2)
    for k in (1, 2):
        d.mark(k)
        until_evaluated(d, k)
    d.mark(4)  # step 3 skipped
    st = d.status()
    assert st["verdict"] == "BLOCKED"
    assert st["stamp"]["reasons"] == ["PROC-SEQUENCE: step 4 marked before step 3 was verified"]
    done = [e["payload"] for e in d.log.events("s1") if e["kind"] == "step_done"]
    assert done[-1] == {"k": 4, "by": "op", "out_of_order": True}
    assert replay(d.log, "s1", PARAMS) == []
    d.mark(3)  # after a terminal verdict marks stay refused
    assert d.status()["refused"][-1]["reason"] == "verdict is already BLOCKED"


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


def slow_mode_switch(ps):
    """Batch p1 S1 seed 260352266: manual mode reached the PLC 1.25 s (12.5 process-s) after the mark. The
    driver marks one poll (2.5 process-s) after this signal function starts."""
    return steady(pressure=2700.0, manual_mode=0.0 if ps < 2.5 + 12.5 else 1.0)


def test_settle_floor_in_wall_time_absorbs_a_slow_mode_switch(tmp_path):
    d = Driver(tmp_path)
    d.run(2)
    d.mark(1, slow_mode_switch)
    until_evaluated(d, 1)
    assert d.status()["steps"][1] == "PASS" and d.status()["verdict"] is None
    assert replay(d.log, "s1", PARAMS) == []


def test_without_the_floor_the_slow_switch_blocks_and_replays(tmp_path):
    d = Driver(tmp_path)
    d.s.params = {**PARAMS, "min_settle_wall_s": 0}  # the batch p1 engine: settle 10 process-s = 1 s wall at x10
    d.run(2)
    d.mark(1, slow_mode_switch)
    until_evaluated(d, 1)
    assert d.status()["verdict"] == "BLOCKED"
    assert replay(d.log, "s1", PARAMS) == []  # logged with no floor, replayed with today's params: same result


def test_verdict_never_improves_and_sign_closes(tmp_path):
    d = Driver(tmp_path)
    d.run(2)
    d.mark(1, lambda ps: steady(pressure=2700.0, manual_mode=0.0))  # S6-like: manual mode never set
    until_evaluated(d, 1)
    assert d.status()["verdict"] == "BLOCKED"
    d.fn = lambda ps: steady(pressure=2700.0)
    d.run(5)
    assert d.status()["verdict"] == "BLOCKED"
    d.run(POLL, [{"kind": "sign", "by": "receiver-a", "role": "receiver", "outcome": "accepted"}])
    st = d.status()  # "accepted" on a block is refused and leaves the session open
    assert st["state"] == "ready" and st["refused"][-1]["outcome"] == "accepted"
    d.run(POLL, [{"kind": "sign", "by": "receiver-a", "role": "receiver"}])
    st = d.status()
    assert st["state"] == "closed" and st["signature"]["verdict_at_signing"] == "BLOCKED"
    assert st["signature"]["outcome"] == "not_accepted"


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


def test_a_start_the_core_refuses_is_logged_under_the_api_id(tmp_path, monkeypatch):
    from zerostate import cli
    from zerostate.session import Inbox

    for var, sub in (("ZS_DATA", "data"), ("ZS_AUDIT", "audit.sqlite"), ("ZS_CONFIG", "config")):
        monkeypatch.setenv(var, str(tmp_path / sub))
    (tmp_path / "data").mkdir()
    Inbox(tmp_path / "data" / "inbox.sqlite").put("api-1", "session_start", plant="p2_gasline", plan_hash="c" * 64,
                                                   by="Owner", plan_check_override=None)
    assert cli.main(["session", "start", "--session", "api-1", "--from-inbox"]) == 1
    ev = AuditLog(tmp_path / "audit.sqlite").events("api-1")
    assert [e["kind"] for e in ev] == ["session_refused"] and "no plan file" in ev[0]["payload"]["reason"]
    assert status_from_events(ev)["state"] == "refused"


def test_accepted_waits_for_pending_camera_reads(tmp_path):
    """Both tracks at NO DISCREPANCY but camera reads still out: the camera may yet block, so "accepted" is
    refused (logged) and the session stays open; once the reads are in, it signs."""
    d = Driver(tmp_path)
    clean_run(d)
    assert d.status()["verdict"] == "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"
    d.s.camera_pending = 2
    d.run(POLL, [{"kind": "sign", "by": "receiver-a", "role": "receiver", "outcome": "accepted"}])
    st = d.status()
    assert st["state"] != "closed" and st["refused"][-1]["reason"] == "camera still checking: 2 reads pending"
    d.s.camera_pending = 0
    d.run(POLL, [{"kind": "sign", "by": "receiver-a", "role": "receiver", "outcome": "accepted"}])
    st = d.status()
    assert st["state"] == "closed" and st["signature"]["outcome"] == "accepted"
    assert replay(d.log, "s1", PARAMS) == []
