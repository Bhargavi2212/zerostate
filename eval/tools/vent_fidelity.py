"""P1-2 (rev 3 criterion): does time compression change the open-loop physics we score?

For each scale: recreate the patched simulator, warm up in AUTO, then in the PLC's manual mode close
f1, f2 and product and open purge to 100 %; log true pressure until it reaches 102 kPa. Compare the
vent time and the pressure curve (in process seconds) between scales and with the physics estimate
dP/dt = -1003 sqrt(P - 100) kPa per process-hour. Pass = everything within 10 %.

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
TARGET_KPA, CURVE_PS, TOL_PCT = 102.0, (60, 120, 180, 240, 300), 10.0
K_VENT = 1003 / 2 / 3600  # d sqrt(P - 100) / d process-s with purge at 100 %


def operator(*args: str) -> None:
    subprocess.run(["docker", "exec", "zs-operator", "python", "operator.py", *args], check=True,
                   capture_output=True, timeout=1800)


def physics_vent_s(p0: float, target: float = TARGET_KPA) -> float:
    return (math.sqrt(p0 - 100) - math.sqrt(target - 100)) / K_VENT


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
    reached = next((ps for ps, p in rows if p <= TARGET_KPA), None)
    curve = {str(c): min(rows, key=lambda r: abs(r[0] - c))[1] for c in CURVE_PS}
    return {"p0": p0, "vent_s": reached, "physics_vent_s": physics_vent_s(p0), "curve": curve, "n": len(rows)}


def judge(results: dict) -> dict:
    out, ref = {}, results.get("1.0")
    for scale, r in results.items():
        reasons = []
        if r["vent_s"] is None:
            reasons.append("never reached the target")
        else:
            err = 100 * abs(r["vent_s"] - r["physics_vent_s"]) / r["physics_vent_s"]
            if err > TOL_PCT:
                reasons.append(f"vent time {r['vent_s']:.0f} process-s vs physics {r['physics_vent_s']:.0f} ({err:.0f} %)")
            if ref and scale != "1.0" and ref["vent_s"]:
                err = 100 * abs(r["vent_s"] - ref["vent_s"]) / ref["vent_s"]
                if err > TOL_PCT:
                    reasons.append(f"vent time {r['vent_s']:.0f} vs x1 {ref['vent_s']:.0f} process-s ({err:.0f} %)")
                for c, p in r["curve"].items():
                    gauge = max(ref["curve"][c] - 100, 1.0)
                    if 100 * abs(p - ref["curve"][c]) / gauge > TOL_PCT:
                        reasons.append(f"P at {c} process-s {p:.0f} vs x1 {ref['curve'][c]:.0f} kPa")
        out[scale] = {"pass": not reasons, "reasons": reasons}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scales", type=float, nargs="+", default=[1.0, 10.0])
    ap.add_argument("--warmup-s", type=float, default=150)
    a = ap.parse_args()
    out = ROOT / "eval" / "results" / f"vent_fidelity_{datetime.now(UTC):%Y-%m-%d}.json"
    results = json.loads(out.read_text(encoding="utf-8"))["results"] if out.exists() else {}
    for scale in a.scales:
        print(f"x{scale}: vent", flush=True)
        results[str(scale)] = vent(scale, a.warmup_s)
        print(json.dumps(results[str(scale)]), flush=True)
    verdict = judge(results)
    out.write_text(json.dumps({"results": results, "verdict": verdict}, indent=1), encoding="utf-8")
    print(json.dumps(verdict, indent=1))
    ts.recreate_simulation(float(os.environ.get("ZS_TIME_SCALE", "1")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
