"""`zs` command line. Run inside the zerostate container, e.g. `docker exec -u zs zerostate zs status s1 --json`.

Paths come from the environment: ZS_DATA (default /data), ZS_MAP and ZS_THRESHOLDS (plant files
copied into the image under /app/config/<plant>/); the map's `protocol` picks the adapter.
"""

import argparse
import json
import os
import sys
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


def _thresholds() -> dict:
    return load_thresholds(os.environ.get("ZS_THRESHOLDS", "/app/config/p1_grfics/thresholds.yaml"))


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


def session_start(a) -> int:
    log = AuditLog(_audit())
    if log.events(a.session):
        print(f"session {a.session} already exists", file=sys.stderr)
        return 1
    raw = yaml.safe_load(Path(a.plan).read_text(encoding="utf-8-sig"))
    plan = IsolationPlan.model_validate(raw.get("plan", raw))  # a plans/<hash>.json from a confirmed draft holds {plan, ...}
    confirmation = is_confirmed(plan.content_hash(), [Path(a.plan).parent, _config() / plan.plant], _data())
    if confirmation is None:
        print(f"refused: plan {plan.content_hash()} is not confirmed by a person (zs plan confirm)", file=sys.stderr)
        return 1
    adapter = open_adapter(os.environ.get("ZS_MAP", "/app/config/p1_grfics/modbus_map.yaml"))
    spans = {e.tag: (e.scale_min, e.scale_max) for e in adapter.map.tags}
    pmap = (PlantMap.model_validate(yaml.safe_load(Path(a.plan_map).read_text(encoding="utf-8-sig")))
            if a.plan_map else None)
    try:
        s = Session(a.session, plan, a.plan_hash, _thresholds(), adapter.map.process_time_scale, spans, log, time.time(),
                    plant_map=pmap, override=a.plan_check_override, confirmation=confirmation)
    except (PlanHashMismatch, PlanCheckFailed) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    inbox = Inbox(_data() / "inbox.sqlite")
    run_dir = _data() / "runs" / a.session
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "signals.jsonl", "a", encoding="utf-8") as out:
        try:
            while not (s.closed or s.stopped):
                t = time.time()
                signals = adapter.read()
                out.write(json.dumps({"t": t, **{k: [v.value, v.raw, v.quality.value] for k, v in signals.items()}}) + "\n")
                s.tick(t, signals, inbox.take(a.session))
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
    st.add_argument("--plan", required=True)
    st.add_argument("--plan-hash", required=True)
    st.add_argument("--session", required=True)
    st.add_argument("--plan-map", help="plant map: run the plan checks before starting")
    st.add_argument("--plan-check-override", help="text accepting a plan-check finding; logged and stamped on every verdict")
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
    api.add_argument("--host", default="0.0.0.0")
    api.add_argument("--port", type=int, default=8090)
    a = ap.parse_args(argv)

    if a.cmd == "api":
        import uvicorn

        from zerostate.api.server import create_app

        uvicorn.run(create_app(_data(), _audit(), _config(), _thresholds()), host=a.host, port=a.port)
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
            inbox.put(a.session, "step_done", k=a.k, by=a.by)
        else:
            inbox.put(a.session, "sign", by=a.by, role=a.role, note=a.note)
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
