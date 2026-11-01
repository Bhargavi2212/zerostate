"""P1-2 (rev 3 criterion): does time compression change the open-loop physics we score?

For each scale: recreate the patched simulator, warm up in AUTO, then in the PLC's manual mode close
f1, f2 and product and open purge to 100 %; log true pressure until it reaches 102 kPa. Compare the
times it takes to fall from a common start (2500 kPa) to each of 1500, 700, 300, 150 and 102 kPa, in
process seconds, between scales and against the physics estimate dP/dt = -1003 sqrt(P - 100) kPa
per process-hour. Aligning on a common start removes the start-pressure offset that AUTO leaves at
each scale. Pass = every time within 10 %.

    python eval/tools/vent_fidelity.py --scales 1 10
"""

import argparse
import importlib.util
import json
import math
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("timescale_test", Path(__file__).parent / "timescale_test.py")
ts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ts)
truth = ts.truth
TARGET_KPA, START_KPA, LEVELS_KPA, TOL_PCT = 102.0, 2500.0, (1500, 700, 300, 150, 102), 10.0
K_VENT = 1003 / 2 / 3600  # d sqrt(P - 100) / d process-s with purge at 100 %


def operator(*args: str) -> None:
    subprocess.run(["docker", "exec", "zs-operator", "python", "operator.py", *args], check=True,
                   capture_output=True, timeout=1800)


def physics_vent_s(p0: float, target: float = TARGET_KPA) -> float:
    return (math.sqrt(p0 - 100) - math.sqrt(target - 100)) / K_VENT


def times_from_start(rows: list[tuple[float, float]]) -> dict | None:
    """Process seconds from the first crossing of START_KPA to the first crossing of each level."""
    t0 = next((ps for ps, p in rows if p <= START_KPA), None)
    if t0 is None:
        return None
    return {str(lv): next((ps - t0 for ps, p in rows if ps >= t0 and p <= lv), None) for lv in LEVELS_KPA}


def vent(scale: float, warmup_s: float) -> dict:
    ts.recreate_simulation(scale)
    time.sleep(warmup_s)
    assert truth.read()["state"]["zs_time_scale"] == scale
    operator("manual", "on")
    for v in ("f1", "f2", "product"):
        operator("set", v, "0")
    time.sleep(10 / scale + 2)  # let the closures settle (10 process-s)
    rows, t0 = [], None
    with truth.stream(4) as samples:  # VM-clock timestamps from inside the container
        operator("set", "purge", "100")
        for d in samples:
            t0 = t0 or d["t"]  # first sample after the purge command returned
            rows.append(((d["t"] - t0) * scale, d["outputs"]["pressure"]))
            if rows[-1][1] <= TARGET_KPA or rows[-1][0] > 1200:
                break
    operator("set", "purge", "0")
    operator("manual", "off")
    p0 = rows[0][1]
    return {"p0": p0, "vent_s": next((ps for ps, p in rows if p <= TARGET_KPA), None),
            "physics_vent_s": physics_vent_s(p0), "times": times_from_start(rows), "rows": rows}


def judge(results: dict) -> dict:
    physics = {str(lv): physics_vent_s(START_KPA, lv) for lv in LEVELS_KPA}
    ref = results.get("1.0")
    out = {}
    for scale, r in results.items():
        reasons = []
        times = r.get("times") or {}
        for lv, t_phys in physics.items():
            t = times.get(lv)
            if t is None:
                reasons.append(f"never reached {lv} kPa from {START_KPA:g}")
                continue
            if 100 * abs(t - t_phys) / t_phys > TOL_PCT:
                reasons.append(f"{START_KPA:g}->{lv} kPa took {t:.0f} process-s vs physics {t_phys:.0f}")
            t_ref = (ref.get("times") or {}).get(lv) if ref and scale != "1.0" else None
            if t_ref and 100 * abs(t - t_ref) / t_ref > TOL_PCT:
                reasons.append(f"{START_KPA:g}->{lv} kPa took {t:.0f} process-s vs x1 {t_ref:.0f}")
        out[scale] = {"pass": not reasons, "reasons": reasons}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scales", type=float, nargs="+", default=[1.0, 10.0])
    ap.add_argument("--warmup-s", type=float, default=150)
    a = ap.parse_args()
    out = ROOT / "eval" / "results" / f"vent_fidelity_{datetime.now(UTC):%Y-%m-%d}.json"
    results = {}  # rerun every scale: aligned comparisons need the full curves
    for scale in a.scales:
        print(f"x{scale}: vent", flush=True)
        results[str(scale)] = vent(scale, a.warmup_s)
        print(json.dumps({k: v for k, v in results[str(scale)].items() if k != "rows"}), flush=True)
    verdict = judge(results)
    out.write_text(json.dumps({"results": results, "verdict": verdict}, indent=1), encoding="utf-8")
    print(json.dumps(verdict, indent=1))
    ts.recreate_simulation(float(os.environ.get("ZS_TIME_SCALE", "1")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
