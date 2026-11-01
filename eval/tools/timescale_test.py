"""P1-2: is the patched GRFICS stable at a compressed time scale? Runs on the host.

For each scale: recreate the simulation container with ZS_TIME_SCALE, warm up, then log truth
at 2 Hz with the PLC in AUTO. A scale passes when pressure and level means are within ±5 % of
nominal, the last-5-min standard deviation is ≤ 2× the first-5-min one, and its standard
deviation is ≤ 3× the ×1 run's.

    python eval/tools/timescale_test.py --scales 1 10 [--minutes 15] [--warmup-s 120]
"""

import argparse
import importlib.util
import json
import os
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[2]
GRFICS = ROOT.parent  # D:\grfics, where Fortiphyd's compose file lives
NOMINAL = {"pressure": 2700.0, "liquid_level": 44.0}

spec = importlib.util.spec_from_file_location("truth", ROOT / "plants" / "p1_grfics" / "truth.py")
truth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(truth)


def recreate_simulation(scale: float) -> None:
    env = {**os.environ, "ZS_TIME_SCALE": str(scale)}
    subprocess.run(["docker", "compose", "-f", "docker-compose.yml", "-f",
                    str(ROOT / "deploy" / "docker-compose.zerostate.yml"),
                    "up", "-d", "--force-recreate", "--no-deps", "simulation"],
                   cwd=GRFICS, env=env, check=True, capture_output=True)


def log_truth(seconds: float, hz: float = 2.0) -> list[dict]:
    rows, end = [], time.monotonic() + seconds
    while time.monotonic() < end:
        t0 = time.monotonic()
        try:
            o = truth.read()["outputs"]
            rows.append({"t": t0, "pressure": o["pressure"], "liquid_level": o["liquid_level"]})
        except OSError:
            pass  # a missed sample is fine; the stats use what arrived
        time.sleep(max(0.0, 1 / hz - (time.monotonic() - t0)))
    return rows


def stats(rows: list[dict]) -> dict:
    t0, t_end = rows[0]["t"], rows[-1]["t"]
    first = [r for r in rows if r["t"] - t0 <= 300]
    last = [r for r in rows if t_end - r["t"] <= 300]
    out = {}
    for k, nominal in NOMINAL.items():
        out[k] = {
            "mean": statistics.fmean(r[k] for r in rows),
            "mean_err_pct": 100 * abs(statistics.fmean(r[k] for r in rows) - nominal) / nominal,
            "sd": statistics.pstdev(r[k] for r in rows),
            "sd_first5": statistics.pstdev(r[k] for r in first),
            "sd_last5": statistics.pstdev(r[k] for r in last),
        }
    return out


def judge(results: dict) -> dict:
    """Pass/fail per scale; the ×1 run is the reference for the ×N sd criterion."""
    ref = results.get("1.0")
    verdict = {}
    for scale, r in results.items():
        reasons = []
        for k, s in r["stats"].items():
            if s["mean_err_pct"] > 5:
                reasons.append(f"{k} mean off nominal by {s['mean_err_pct']:.1f} %")
            if s["sd_last5"] > 2 * max(s["sd_first5"], 1e-9):
                reasons.append(f"{k} sd grew: last 5 min {s['sd_last5']:.3g} > 2 × first {s['sd_first5']:.3g}")
            if ref and scale != "1.0" and s["sd"] > 3 * max(ref["stats"][k]["sd"], 1e-9):
                reasons.append(f"{k} sd {s['sd']:.3g} > 3 × ×1 sd {ref['stats'][k]['sd']:.3g}")
        verdict[scale] = {"pass": not reasons, "reasons": reasons}
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scales", type=float, nargs="+", default=[1.0, 10.0])
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--warmup-s", type=float, default=120)
    args = ap.parse_args()

    out = ROOT / "eval" / "results" / f"timescale_{datetime.now(UTC):%Y-%m-%d}.json"
    # Keep earlier runs from the same day (e.g. the x1 reference) so a later scale is judged against them.
    results = json.loads(out.read_text(encoding="utf-8"))["results"] if out.exists() else {}
    for scale in args.scales:
        print(f"scale ×{scale}: recreating simulation, warming up {args.warmup_s:.0f} s", flush=True)
        recreate_simulation(scale)
        time.sleep(args.warmup_s)
        assert truth.read()["state"].get("zs_time_scale") == scale, "simulation did not take the scale"
        rows = log_truth(args.minutes * 60)
        results[str(scale)] = {"n": len(rows), "stats": stats(rows)}
        print(json.dumps(results[str(scale)]["stats"], indent=1), flush=True)

    verdict = judge(results)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"minutes": args.minutes, "warmup_s": args.warmup_s,
                               "results": results, "verdict": verdict}, indent=1), encoding="utf-8")
    print(json.dumps(verdict, indent=1))
    recreate_simulation(1.0)  # leave the lab at real time until the decision is recorded
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
