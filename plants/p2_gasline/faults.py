"""Eval only: P2 faults through the server's unix socket inside the container (never the network):
    docker exec -i zs-p2 python3 - /run/p2/control.sock '<json request>'   (CLIENT on stdin)

Fault keys (model.GasLine.set): '<PT>.fault_mode' 1 frozen / 2 drift (severity per process-hour) / 4 dropout
(severity = dropped fraction of each 10 process-s), '<PT>.fault_severity', '<V>.pos_fault_mode' 1 frozen /
2 offset / 3 fixed, '<V>.pos_fault_severity', '<V>.leak_pct', '<V>.stuck', 'VV-213.flow_scale',
'S-200.pressure_kpa', 'D-220.pressure_kpa'. S12 is `updates(False)`: the server stops publishing.
"""

import json
import subprocess
import sys

CONTAINER, SOCKET = "zs-p2","/run/p2/control.sock"
CLIENT = """
import socket, sys
s = socket.socket(socket.AF_UNIX)
s.settimeout(5)
s.connect(sys.argv[1])
s.sendall(sys.argv[2].encode() + b"\\n")
print(s.makefile().readline(), end="")
"""
SENSORS = ("PT-200", "PT-202", "PT-211", "PT-212", "FT-213")
VALVES = ("XV-201", "BV-202", "XV-203", "VV-213", "XV-204", "XV-231")
CLEAR = {**{f"{s}.fault_mode": 0 for s in SENSORS}, **{f"{s}.fault_severity": 0 for s in SENSORS},
         **{f"{v}.pos_fault_mode": 0 for v in VALVES}, **{f"{v}.pos_fault_severity": 0 for v in VALVES},
         **{f"{v}.leak_pct": 0 for v in VALVES}, **{f"{v}.stuck": 0 for v in VALVES},
         "VV-213.flow_scale": 1, "S-200.pressure_kpa": 2000, "D-220.pressure_kpa": 1500}


def request(req: dict) -> dict:
    r = subprocess.run(["docker", "exec", "-i", CONTAINER, "python3", "-", SOCKET, json.dumps(req)],
                       input=CLIENT, capture_output=True, text=True, timeout=15, check=True)
    reply = json.loads(r.stdout)
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return reply


def set_inputs(**inputs) -> dict:
    return request({"request": "set", "data": inputs})


def clear() -> dict:
    set_inputs(**CLEAR)
    return updates(True)


def updates(on: bool) -> dict:
    return request({"request": "updates", "on": on})


def read() -> dict:
    return request({"request": "read"})


if __name__ == "__main__":
    # python plants/p2_gasline/faults.py read | clear | stop_updates | set XV-204.leak_pct=0.5 ...
    cmd = sys.argv[1]
    if cmd == "read":
        print(json.dumps(read(), indent=1))
    elif cmd == "clear":
        clear()
    elif cmd == "stop_updates":
        updates(False)
    elif cmd == "set":
        set_inputs(**{k: float(v) for k, v in (a.split("=", 1) for a in sys.argv[2:])})
