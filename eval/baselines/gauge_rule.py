"""Gauge-rule baseline (a hurried person reading the gauges), pinned before running (plan G23): at the
last step mark, pass when MEASURED pressure < 150 kPa and every measured flow <= its meter cutoff (1 % of
the line's full scale); otherwise block. A missing reading blocks. Signals are the ones the episode
bundle carries (what ZeroState read). Scored by eval/score.py with the same hazard code.

    python eval/baselines/gauge_rule.py eval/results/bench/p1/<episode> ...
"""

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
PRESSURE_KPA = 150.0
CUTOFF = 0.01  # meter cutoff: 1 % of full scale


def _bundle():
    spec = importlib.util.spec_from_file_location("export_bundle", ROOT / "eval" / "tools" / "export_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


export_bundle = _bundle()


def full_scale(plant: str) -> dict:
    tags = yaml.safe_load((ROOT / "plants" / plant / "modbus_map.yaml").read_text(encoding="utf-8"))["tags"]
    return {t["tag"]: t["scale_max"] for t in tags if t["tag"].endswith("_flow")}


def at(signals: dict, tag: str, t: float):
    """The sample nearest to t (signals are <= 1 Hz)."""
    pts = [(abs(ts - t), v) for ts, v in zip(signals["t"], signals.get(tag, []), strict=False) if v is not None]
    return min(pts, key=lambda p: p[0])[1] if pts else None


def decide(run: Path) -> dict:
    audit = json.loads((Path(run) / "audit_export.json").read_text(encoding="utf-8"))
    marks = [datetime.fromisoformat(e["ts"]).timestamp() for e in audit if e["kind"] == "step_done"]
    b = export_bundle.build(Path(run))
    if not marks:
        return {"answer": "block", "t": None, "why": "no step marked"}
    t, cutoffs = max(marks), {tag: CUTOFF * fs for tag, fs in full_scale(b.plant).items()}
    values = {tag: at(b.signals, tag, t) for tag in ["pressure", *cutoffs]}
    ok = None not in values.values() and values["pressure"] < PRESSURE_KPA and all(
        values[tag] <= c for tag, c in cutoffs.items())
    return {"answer": "pass" if ok else "block", "t": t, "values": values}


if __name__ == "__main__":
    for r in sys.argv[1:]:
        print(Path(r).name, json.dumps(decide(Path(r))))
