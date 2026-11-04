"""`zs` command line. Run inside the zerostate container, e.g. `docker exec -u zs zerostate zs status s1 --json`.

Paths come from the environment: ZS_DATA (default /data), ZS_MAP and ZS_THRESHOLDS (plant files
copied into the image under /app/config/<plant>/, set by deploy/Dockerfile or per episode; no plant
default here); the map's `protocol` picks the adapter.
"""

import argparse
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

import yaml

from zerostate.adapters.modbus import ModbusReadOnly
from zerostate.adapters.opcua import OpcUaReadOnly
from zerostate.audit.log import AuditLog
from zerostate.audit.replay import replay
from zerostate.config import load_thresholds
from zerostate.importers.confirm import is_confirmed
from zerostate.models.envelope import IsolationPlan
from zerostate.models.plant_map import PlantMap
from zerostate.session import Inbox, PlanCheckFailed, PlanHashMismatch, Session, status_from_events

POLL_WALL_S = 0.25  # 4 Hz


def _data() -> Path:
    d = Path(os.environ.get("ZS_DATA", "/data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _audit() -> Path:
    """ZS_AUDIT: the audit log on its own volume (zerostate rw, zs-api ro); default unchanged."""
    return Path(os.environ.get("ZS_AUDIT", _data() / "audit.sqlite"))


def _env_path(name: str) -> str:
    """A plant file named by the environment only: the engine carries no plant default."""
    if not os.environ.get(name):
        raise SystemExit(f"{name} is not set: point it at the plant's file under /app/config/<plant>/")
    return os.environ[name]


def _thresholds() -> dict:
    return load_thresholds(_env_path("ZS_THRESHOLDS"))


def _config() -> Path:
    return Path(os.environ.get("ZS_CONFIG", "/app/config"))


def plan_cmd(a) -> int:
    """zs plan import / show / confirm. Model routes are imported here only, never on the session path."""
    from zerostate.importers import confirm as cf
    from zerostate.importers import draft as dr
    from zerostate.llm.client import ModelUnavailable

    def plant_map(plant):
        path = Path(a.map or _config() / plant / "plant_map.yaml")
        return PlantMap.model_validate(yaml.safe_load(path.read_text(encoding="utf-8-sig")))

    try:
        if a.action == "confirm":
            rec = cf.confirm(a.target, a.by, a.role, data_dir=_data(), config_dir=_config(), map_path=a.map, params=_thresholds())
            print(rec["plan_hash"])
            return 0
        if a.action == "import":
            from zerostate.importers.csv_import import parse_csv
            from zerostate.importers.image_import import import_image
            from zerostate.importers.text_import import import_text

            pmap, transcript = plant_map(a.plant), None
            if a.csv:
                lst, route, src = parse_csv(a.csv, a.plant), "csv", a.csv
            elif a.text:
                lst, route, src = import_text(Path(a.text).read_text(encoding="utf-8-sig"), pmap), "text", a.text
            else:
                (lst, transcript), route, src = import_image(a.image, pmap), "image", a.image
            a.draft = dr.save_draft(lst, route, Path(src).name, _data(), transcript)["id"]
        d = dr.load_draft(a.draft, _data())
        print(json.dumps(dr.check_draft(d, plant_map(d["list"]["plant"]), _thresholds())[1], indent=2))
        return 0
    except (ValueError, OSError, yaml.YAMLError, ModelUnavailable) as e:  # bad input, no model, unresolved draft
        print(f"refused: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


def open_adapter(map_path: str | Path):
    """The plant map names its protocol; no `protocol` key means Modbus (P1's map predates it)."""
    proto = (yaml.safe_load(Path(map_path).read_text(encoding="utf-8-sig")) or {}).get("protocol", "modbus")
    return OpcUaReadOnly(map_path) if proto == "opcua" else ModbusReadOnly(map_path)


def camera_track(s, plan, log, scale, override):
    """The with-camera track, only when the plan declares a camera. With ZS_FRAMES_URL set: a worker thread
    captures and reads; without it: one UNKNOWN camera evaluation is logged (it escalates the with-camera
    track only when the camera is required). Camera code is imported here only, never on the data-only path."""
    if not plan.camera:
        return None, None, None
    from zerostate.camera import track as ct

    if not os.environ.get("ZS_FRAMES_URL"):
        ct.CameraTrack(s.sid, plan, s.params, log, {}, scale, override).no_service()
        return None, None, None
    dmap = ct.load_display_map(os.environ.get("ZS_DISPLAY_MAP", str(_config() / "frame_service" / "display_map.yaml")))
    cam = ct.CameraTrack(s.sid, plan, s.params, log, dmap, scale, override, frames_dir=_data() / "frames" / s.sid)
    jobs, results = queue.Queue(), queue.Queue()
    threading.Thread(target=ct.worker, args=(jobs, results), daemon=True, name="camera").start()
    return cam, jobs, results


def _load_plan(path: Path) -> IsolationPlan:
    raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    return IsolationPlan.model_validate(raw.get("plan", raw))  # a plans/<hash>.json from a confirmed draft holds {plan, ...}


def _plan_file(plant: str, plan_hash: str) -> Path | None:
    """The plan file for a hash: a confirmed draft (/data/plans/<hash>.json) or a plan YAML in the plant config."""
    p = _data() / "plans" / f"{plan_hash}.json"
    if p.exists():
        return p
    for y in sorted((_config() / plant).glob("*.yaml")):
        try:
            h = _load_plan(y).content_hash()
        except Exception:  # noqa: BLE001 - not a plan file
            h = None
        if h == plan_hash:
            return y
    return None


def _from_inbox(a, log: AuditLog) -> str | None:
    """Fill the start arguments from the request the API queued; returns a refusal reason, or None."""
    req = Inbox(_data() / "inbox.sqlite").start_request(a.session)
    if req is None:
        return f"no session start queued for {a.session}"
    path = _plan_file(req["plant"], req["plan_hash"])
    if path is None:
        return f"no plan file with hash {req['plan_hash']} for {req['plant']}"
    a.plan, a.plan_hash, a.plan_check_override = str(path), req["plan_hash"], req.get("plan_check_override")
    pmap = _config() / req["plant"] / "plant_map.yaml"
    a.plan_map = a.plan_map or (str(pmap) if pmap.exists() else None)
    return None


def session_start(a) -> int:
    log = AuditLog(_audit())
    if log.events(a.session):
        print(f"session {a.session} already exists", file=sys.stderr)
        return 1

    def refuse(reason: str) -> int:
        print(f"refused: {reason}", file=sys.stderr)
        if a.from_inbox:  # the API returned this id: say why it never started
            log.append(a.session, "session_refused", {"reason": reason})
        return 1

    if a.from_inbox:
        why = _from_inbox(a, log)
        if why:
            return refuse(why)
    elif not (a.plan and a.plan_hash):
        print("session start needs --plan and --plan-hash, or --from-inbox", file=sys.stderr)
        return 2
    plan = _load_plan(Path(a.plan))
    confirmation = is_confirmed(plan.content_hash(), [Path(a.plan).parent, _config() / plan.plant], _data())
    if confirmation is None:
        return refuse(f"plan {plan.content_hash()} is not confirmed by a person (zs plan confirm)")
    adapter = open_adapter(_env_path("ZS_MAP"))
    spans = {e.tag: (e.scale_min, e.scale_max) for e in adapter.map.tags}
    pmap = (PlantMap.model_validate(yaml.safe_load(Path(a.plan_map).read_text(encoding="utf-8-sig")))
            if a.plan_map else None)
    try:
        s = Session(a.session, plan, a.plan_hash, _thresholds(), adapter.map.process_time_scale, spans, log, time.time(),
                    plant_map=pmap, override=a.plan_check_override, confirmation=confirmation)
    except (PlanHashMismatch, PlanCheckFailed) as e:
        adapter.close()
        return refuse(str(e))
    inbox = Inbox(_data() / "inbox.sqlite")
    run_dir = _data() / "runs" / a.session
    run_dir.mkdir(parents=True, exist_ok=True)
    cam, jobs, results = camera_track(s, plan, log, adapter.map.process_time_scale, a.plan_check_override)
    with open(run_dir / "signals.jsonl", "a", encoding="utf-8") as out:
        try:
            while not (s.closed or s.stopped):
                t = time.time()
                signals = adapter.read()
                out.write(json.dumps({"t": t, **{k: [v.value, v.raw, v.quality.value] for k, v in signals.items()}}) + "\n")
                s.tick(t, signals, inbox.take(a.session))
                if cam is not None:  # never waits on the worker: the 4 Hz poll only queues and collects
                    cam.observe(t, signals)
                    for job in cam.due(t, s.marks, s.steps, s.verdict):
                        jobs.put(job)
                    while not results.empty():
                        for res in results.get_nowait():
                            cam.record(res, s.verdict)
                    s.camera_verdict = cam.verdict
                time.sleep(max(0.0, POLL_WALL_S - (time.time() - t)))
        except Exception as e:
            s.fail(f"{type(e).__name__}: {e}")
            raise
        finally:
            adapter.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="zs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    se = sub.add_parser("session").add_subparsers(dest="action", required=True)
    st = se.add_parser("start")
    st.add_argument("--plan")
    st.add_argument("--plan-hash")
    st.add_argument("--session", required=True)
    st.add_argument("--from-inbox", action="store_true", help="start the session the API queued under --session (POST /api/sessions)")
    st.add_argument("--plan-map", help="plant map: run the plan checks before starting")
    st.add_argument("--plan-check-override", help="text accepting a plan-check finding; logged and stamped on every verdict")
    stop = se.add_parser("stop")
    stop.add_argument("session")
    stop.add_argument("--by", default="eval-runner")
    p = sub.add_parser("status")
    p.add_argument("session")
    p.add_argument("--json", action="store_true")
    sp = sub.add_parser("step").add_subparsers(dest="action", required=True)
    # verify: a second person confirms an isolate step (PROC-INDEPENDENCE); reopen: inch and test (PROC-RESET)
    for name in ("done", "verify", "reopen"):
        sd = sp.add_parser(name)
        sd.add_argument("session")
        sd.add_argument("k", type=int)
        sd.add_argument("--by", required=True)
        if name == "reopen":
            sd.add_argument("--reason", required=True)
    sg = sub.add_parser("sign")
    sg.add_argument("session")
    sg.add_argument("--by", required=True)
    sg.add_argument("--role", required=True, choices=["planner", "approver", "installer", "verifier", "prover", "receiver"])
    sg.add_argument("--note")
    sg.add_argument("--outcome", default="not_accepted", choices=["accepted", "not_accepted"],
                    help="accepted only when both tracks read NO DISCREPANCY FOUND (the core refuses it otherwise)")
    au = sub.add_parser("audit").add_subparsers(dest="action", required=True)
    for name in ("verify", "export"):
        au.add_parser(name).add_argument("session")
    sub.add_parser("replay").add_argument("session")
    ph = sub.add_parser("plan-hash")
    ph.add_argument("plan")
    pl = sub.add_parser("plan").add_subparsers(dest="action", required=True)
    pi = pl.add_parser("import")
    src = pi.add_mutually_exclusive_group(required=True)
    for route in ("--csv", "--text", "--image"):
        src.add_argument(route, metavar="PATH")
    pi.add_argument("--plant", required=True)
    pshow = pl.add_parser("show")
    pshow.add_argument("draft")
    pc = pl.add_parser("confirm")
    pc.add_argument("target", help="plan YAML file or draft id")
    pc.add_argument("--by", required=True)
    pc.add_argument("--role", default="issuer", choices=["issuer"])
    for p_ in (pi, pshow, pc):
        p_.add_argument("--map", help="plant_map.yaml (default /app/config/<plant>/plant_map.yaml)")
    api = sub.add_parser("api", help="HTTP API for the console (docs/API.md); the container publishes it on 127.0.0.1 only")
    api.add_argument("--host", help="default 0.0.0.0 in the container (published on 127.0.0.1 only); 127.0.0.1 with --replay")
    api.add_argument("--port", type=int, default=8090)
    api.add_argument("--replay", metavar="BUNDLE_DIR", help="serve recorded bundles read-only: no lab, no audit log, no key")
    a = ap.parse_args(argv)

    if a.cmd == "api":
        import uvicorn

        from zerostate.api.server import create_app

        if a.replay:  # nothing is written in replay mode: the bundle dir stands in for the data dir
            app = create_app(a.replay, Path(a.replay) / "no-audit.sqlite", _config(), {}, replay_dir=a.replay)
        else:
            app = create_app(_data(), _audit(), _config(), _thresholds())
        uvicorn.run(app, host=a.host or ("127.0.0.1" if a.replay else "0.0.0.0"), port=a.port)
        return 0

    if a.cmd == "session" and a.action == "start":
        return session_start(a)
    if a.cmd == "plan":
        return plan_cmd(a)
    if a.cmd == "plan-hash":
        print(IsolationPlan.model_validate(yaml.safe_load(Path(a.plan).read_text(encoding="utf-8-sig"))).content_hash())
        return 0
    if a.cmd in ("session", "step", "sign"):
        inbox = Inbox(_data() / "inbox.sqlite")
        if a.cmd == "session":
            inbox.put(a.session, "stop", by=a.by)
        elif a.cmd == "step":
            inbox.put(a.session, f"step_{a.action}", k=a.k, by=a.by, **({"reason": a.reason} if a.action == "reopen" else {}))
        else:
            inbox.put(a.session, "sign", by=a.by, role=a.role, note=a.note, outcome=a.outcome)
        return 0
    log = AuditLog(_audit())
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
            if "stamp_with_camera" in s or s["camera_pending"]:
                print(f"  with camera: {s['verdict_with_camera'] or '-'}  (camera reads pending: {s['camera_pending']})")
                for r in s.get("stamp_with_camera", {}).get("reasons", []):
                    print(f"  camera reason: {r}")
            if (s["stamp"] or {}).get("plan_check_override"):
                print(f"  plan-check override: {s['stamp']['plan_check_override']}")
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
