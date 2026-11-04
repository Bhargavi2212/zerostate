"""Camera accuracy set (C7): the operator puts the P1 valves at random positions in manual mode, then one
frame and its truth sidecar are captured per position. Tuning lab session, never scoring. Frames and
sidecars are stored OUTSIDE git; only their hash list is committed (eval/frames_set/hashes.txt).

    python eval/tools/capture_frames.py --n 100 --seed 1 --out D:/grfics/frames_set
    git add eval/frames_set/hashes.txt   # before any frame is read by a model

Needs the lab: simulation, zs-operator and zs-frames running. Leaves the plant in AUTO.
"""

import argparse
import hashlib
import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parents[2]
VALVES = ("f1", "f2", "purge", "product")
GRAB = ("import sys, urllib.request as u; r = u.urlopen('http://localhost:8080/frame?view=' + sys.argv[1], timeout=100); "
        "sys.stderr.write(r.headers['X-Capture-Id']); sys.stdout.buffer.write(r.read())")


def operator(*args) -> None:
    subprocess.run(["docker", "exec", "zs-operator", "python", "operator.py", *args], check=True, capture_output=True, timeout=600)


def grab(view: str) -> tuple[bytes, str]:
    r = subprocess.run(["docker", "exec", "zs-frames", "python", "-c", GRAB, view], check=True, capture_output=True, timeout=150)
    return r.stdout, r.stderr.decode().strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, required=True, help="tuning seed (< 1000)")
    ap.add_argument("--out", type=Path, required=True, help="outside the repo")
    ap.add_argument("--view", default="default")
    ap.add_argument("--settle-wall-s", type=float, default=15, help="valve travel + the page's 3 s poll")
    ap.add_argument("--values", help="comma list: draw each valve's position from these (e.g. a zero-heavy set) instead of 0-100")
    ap.add_argument("--hashes-out", type=Path, default=ROOT / "eval" / "frames_set" / "hashes.txt")
    a = ap.parse_args(argv)
    if a.seed >= 1000 or ROOT in a.out.resolve().parents:
        raise SystemExit("tuning seeds only, and frames are stored outside the repo")
    a.out.mkdir(parents=True, exist_ok=True)
    rng, hashes = random.Random(a.seed), []
    pool = [float(x) for x in a.values.split(",")] if a.values else None
    operator("manual", "on")
    try:
        for i in range(a.n):
            pos = {v: (float(rng.choice(pool)) if pool else round(rng.uniform(0, 100), 1)) for v in VALVES}
            for v, p in pos.items():
                operator("set", v, str(p))
            time.sleep(a.settle_wall_s)
            jpeg, cid = grab(a.view)
            name = f"frame_{i:03d}"
            (a.out / f"{name}.jpg").write_bytes(jpeg)
            subprocess.run(["docker", "cp", f"zs-frames:/truth/{cid}.json", str(a.out / f"{name}.truth.json")], check=True)
            (a.out / f"{name}.set.json").write_text(json.dumps({"view": a.view, "commanded": pos, "capture_id": cid}))
            hashes += [f"{hashlib.sha256((a.out / f).read_bytes()).hexdigest()}  {f}" for f in (f"{name}.jpg", f"{name}.truth.json")]
            print(name, cid, flush=True)
    finally:
        operator("manual", "off")
    dest = a.hashes_out
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(hashes) + "\n", encoding="utf-8")
    print(f"{len(hashes)} frames in {a.out}; hash list {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
