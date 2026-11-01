"""Eval only: P1 ground truth, read from INSIDE the simulation container (GRFICS web API on its own
localhost). Never through the Windows port forward, which Docker Desktop can drop on a container
recreate. Timestamps come from the Docker VM clock, the same clock ZeroState stamps its readings with.

    read()          one sample (one docker exec; fine for occasional checks)
    stream(hz)      one long-running docker exec printing a JSON line per sample: {"t": vm_time, ...}
"""

import json
import subprocess

URL = "http://localhost/data/index.php"
MARK = "zs-truth-loop"  # argv tag so the loop can be ended: killing docker exec leaves it running in the container
LOOP = """
import json, sys, time, urllib.request
period = float(sys.argv[1])
while True:
    t0 = time.time()
    try:
        with urllib.request.urlopen("URL", timeout=2) as r:
            line = json.dumps({"t": t0, **json.loads(r.read())})
    except Exception:
        line = None  # a missed sample is fine
    if line:
        print(line, flush=True)
    time.sleep(max(0.0, period - (time.time() - t0)))
""".replace("URL", URL)


def read(timeout: float = 10.0) -> dict:
    r = subprocess.run(["docker", "exec", "simulation", "curl", "-s", "-m", "3", URL],
                       capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(r.stdout)


class stream:  # lower-case: used like a function, `with truth.stream(4) as samples:`
    """Iterate truth samples from one long-running reader inside the container."""

    def __init__(self, hz: float = 4.0):
        self.proc = subprocess.Popen(["docker", "exec", "-i", "simulation", "python3", "-u", "-", str(1 / hz), MARK],
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
        subprocess.run(["docker", "exec", "simulation", "pkill", "-f", MARK], capture_output=True, check=False)
