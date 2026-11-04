"""Eval only: P2 ground truth from the server's unix socket inside the container (Docker VM clock, the
same clock ZeroState stamps its readings with). Never over the network.

    read()          one sample (one docker exec)
    stream(hz)      one long-running docker exec printing a JSON line per sample: {"t": vm_time, ...}
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from faults import CONTAINER, SOCKET, read  # noqa: F401  (read: one sample)

MARK = "zs-p2-truth-loop"  # argv tag so the loop can be ended: killing docker exec leaves it running
LOOP = """
import json, socket, sys, time
path, period = sys.argv[1], float(sys.argv[2])
while True:
    t0 = time.time()
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(2)
        s.connect(path)
        s.sendall(b'{"request": "read"}\\n')
        line = s.makefile().readline().strip()
        s.close()
    except OSError:
        line = None  # a missed sample is fine
    if line:
        print(line, flush=True)
    time.sleep(max(0.0, period - (time.time() - t0)))
"""


class stream:  # lower-case: used like a function, `with truth.stream(4) as samples:`
    def __init__(self, hz: float = 4.0):
        self.proc = subprocess.Popen(["docker", "exec", "-i", CONTAINER, "python3", "-u", "-", SOCKET, str(1 / hz), MARK],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.proc.stdin.write(LOOP)
        self.proc.stdin.close()

    def __enter__(self):
        return self

    def __iter__(self):
        for line in self.proc.stdout:
            yield json.loads(line)

    def __exit__(self, *exc):
        self.proc.kill()
        self.proc.wait(timeout=10)
        subprocess.run(["docker", "exec", CONTAINER, "pkill", "-f", MARK], capture_output=True, check=False)
