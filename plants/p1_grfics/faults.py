"""Eval only: inject or clear P1 faults through the simulator socket (never the web API, which
holds a newly activated fault 3 s). Faults persist across the remote I/O's own writes."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (Path(__file__).parent / "sim_socket.py").read_text(encoding="utf-8")
MAX_MSG = 1000  # the simulator reads at most 1024 bytes per request
VALVES = ("f1", "f2", "purge", "product")
SENSORS = ("tank_pressure", "tank_level", "f1_flow", "f2_flow", "purge_flow", "product_flow", "analyzer")
CLEAR = {
    **{f"{v}_slew_rate": 0 for v in VALVES},
    **{f"{v}_cv_scale": 1 for v in VALVES},
    **{f"{v}_stuck": 0 for v in VALVES},
    **{f"{s}_fault_mode": 0 for s in SENSORS},
    **{f"{s}_fault_severity": 0 for s in SENSORS},
    **{f"{v}_pos_fault_mode": 0 for v in VALVES},
    **{f"{v}_pos_fault_severity": 0 for v in VALVES},
    **{f"{v}_leak_pct": 0 for v in VALVES},
}


def request(req: dict) -> dict:
    msg = json.dumps(req, separators=(",", ":"))
    assert len(msg) <= MAX_MSG, f"request too long for the simulator ({len(msg)} bytes)"
    r = subprocess.run(["docker", "exec", "-i", "simulation", "python3", "-", msg],
                       input=SCRIPT, capture_output=True, text=True, timeout=15, check=True)
    return json.loads(r.stdout)


def set_inputs(**inputs) -> dict:
    """Write fault inputs, split so each message fits the simulator's buffer."""
    reply, chunk = {}, {}
    for k, v in inputs.items():
        chunk[k] = v
        if len(json.dumps({"request": "write", "data": {"inputs": chunk}})) > MAX_MSG - 40:
            reply = request({"request": "write", "data": {"inputs": chunk}})
            chunk = {}
    if chunk:
        reply = request({"request": "write", "data": {"inputs": chunk}})
    return reply


def clear() -> dict:
    return set_inputs(**CLEAR)


def read() -> dict:
    return request({"request": "read"})


if __name__ == "__main__":
    # python -P plants/p1_grfics/faults.py read | clear | set key=value ...
    # (-P: operator.py next to this file would otherwise shadow the stdlib "operator" module)
    cmd = sys.argv[1]
    if cmd == "read":
        print(json.dumps(read(), indent=1))
    elif cmd == "clear":
        clear()
    elif cmd == "set":
        set_inputs(**{k: float(v) for k, v in (a.split("=", 1) for a in sys.argv[2:])})
