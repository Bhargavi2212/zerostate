"""`zs` command line. Run inside the zerostate container, e.g. `docker exec -u zs zerostate zs status s1 --json`.

Paths come from the environment: ZS_DATA (default /data), ZS_MAP and ZS_THRESHOLDS (plant files
copied into the image under /app/config/<plant>/).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import yaml

from zerostate.adapters.modbus import ModbusReadOnly
from zerostate.audit.log import AuditLog
from zerostate.audit.replay import replay
from zerostate.config import load_thresholds
from zerostate.models.envelope import IsolationPlan
from zerostate.session import Inbox, PlanHashMismatch, Session, status_from_events

POLL_WALL_S = 0.25  # 4 Hz


def _data() -> Path:
    d = Path(os.environ.get("ZS_DATA", "/data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _thresholds() -> dict:
    return load_thresholds(os.environ.get("ZS_THRESHOLDS", "/app/config/p1_grfics/thresholds.yaml"))


def session_start(a) -> int:
    log = AuditLog(_data() / "audit.sqlite")
    if log.events(a.session):
        print(f"session {a.session} already exists", file=sys.stderr)
        return 1
    plan = IsolationPlan.model_validate(yaml.safe_load(Path(a.plan).read_text(encoding="utf-8-sig")))
    adapter = ModbusReadOnly(os.environ.get("ZS_MAP", "/app/config/p1_grfics/modbus_map.yaml"))
    spans = {e.tag: (e.scale_min, e.scale_max) for e in adapter.map.tags}
    try:
        s = Session(a.session, plan, a.plan_hash, _thresholds(), adapter.map.process_time_scale, spans, log, time.time())
    except PlanHashMismatch as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    inbox = Inbox(_data() / "inbox.sqlite")
    run_dir = _data() / "runs" / a.session
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "signals.jsonl", "a", encoding="utf-8") as out:
        while not (s.closed or s.stopped):
            t = time.time()
            signals = adapter.read()
            out.write(json.dumps({"t": t, **{k: [v.value, v.raw, v.quality.value] for k, v in signals.items()}}) + "\n")
            s.tick(t, signals, inbox.take(a.session))
            time.sleep(max(0.0, POLL_WALL_S - (time.time() - t)))
    adapter.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="zs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    se = sub.add_parser("session").add_subparsers(dest="action", required=True)
    st = se.add_parser("start")
    st.add_argument("--plan", required=True)
    st.add_argument("--plan-hash", required=True)
    st.add_argument("--session", required=True)
    stop = se.add_parser("stop")
    stop.add_argument("session")
    stop.add_argument("--by", default="eval-runner")
    p = sub.add_parser("status")
    p.add_argument("session")
    p.add_argument("--json", action="store_true")
    sd = sub.add_parser("step").add_subparsers(dest="action", required=True).add_parser("done")
    sd.add_argument("session")
    sd.add_argument("k", type=int)
    sd.add_argument("--by", required=True)
    sg = sub.add_parser("sign")
    sg.add_argument("session")
    sg.add_argument("--by", required=True)
    sg.add_argument("--role", required=True, choices=["planner", "approver", "installer", "verifier", "prover", "receiver"])
    sg.add_argument("--note")
    au = sub.add_parser("audit").add_subparsers(dest="action", required=True)
    for name in ("verify", "export"):
        au.add_parser(name).add_argument("session")
    sub.add_parser("replay").add_argument("session")
    ph = sub.add_parser("plan-hash")
    ph.add_argument("plan")
    a = ap.parse_args(argv)

    if a.cmd == "session" and a.action == "start":
        return session_start(a)
    if a.cmd == "plan-hash":
        print(IsolationPlan.model_validate(yaml.safe_load(Path(a.plan).read_text(encoding="utf-8-sig"))).content_hash())
        return 0
    if a.cmd in ("session", "step", "sign"):
        inbox = Inbox(_data() / "inbox.sqlite")
        if a.cmd == "session":
            inbox.put(a.session, "stop", by=a.by)
        elif a.cmd == "step":
            inbox.put(a.session, "step_done", k=a.k, by=a.by)
        else:
            inbox.put(a.session, "sign", by=a.by, role=a.role, note=a.note)
        return 0
    log = AuditLog(_data() / "audit.sqlite")
    events = log.events(a.session)
    if not events:
        print(f"no session {a.session}", file=sys.stderr)
        return 1
    if a.cmd == "status":
        s = status_from_events(events)
        if a.json:
            print(json.dumps(s))
        else:
            print(f"{a.session}: {s['state']}  verdict: {s['verdict'] or '-'}")
            for k, v in sorted(s["steps"].items()):
                print(f"  step {k}: {v}")
            for r in (s["stamp"] or {}).get("reasons", []):
                print(f"  reason: {r}")
        return 0
    if a.cmd == "audit" and a.action == "verify":
        ok, bad = log.verify()
        print(f"chain {'ok' if ok else f'broken at event {bad}'}; {len(events)} events in {a.session}")
        return 0 if ok else 1
    if a.cmd == "audit" and a.action == "export":
        print(json.dumps(events))
        return 0
    if a.cmd == "replay":
        mismatches = replay(log, a.session, _thresholds())
        print("replay identical" if not mismatches else "\n".join(mismatches))
        return 0 if not mismatches else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
