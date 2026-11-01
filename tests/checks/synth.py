"""Synthetic P1 windows for rule tests: the P1 plan and thresholds, a simple vent model, 4 Hz polls."""

import math
from pathlib import Path

import yaml

from zerostate.adapters.modbus import load_map
from zerostate.config import load_thresholds
from zerostate.models.envelope import IsolationPlan
from zerostate.models.evidence import Window

P1 = Path(__file__).parents[2] / "plants" / "p1_grfics"
PLAN = IsolationPlan.model_validate(yaml.safe_load((P1 / "envelope.yaml").read_text()))
PARAMS = load_thresholds(P1 / "thresholds.yaml")
MAP = load_map(P1 / "modbus_map.yaml")
SPANS = {e.tag: (e.scale_min, e.scale_max) for e in MAP.tags}
STEP = {s.k: s for s in PLAN.steps}


def vented_pressure(ps: float, p0: float = 2700.0) -> float:
    """dP/dt = -1003 sqrt(P - 100) kPa per process-hour, purge 100 %, everything else closed."""
    root = max(math.sqrt(p0 - 100) - 1003 / 2 / 3600 * ps, 0.0)
    return 100 + root * root


def steady(_ps: float | None = None, **over) -> dict:
    """Isolated, vented plant at ~101 kPa with purge closed; override any tag."""
    base = {"pressure": 101.0, "manual_mode": 1.0}
    for v in ("f1", "f2", "purge", "product"):
        base |= {f"{v}_valve_pos": 0.0, f"{v}_cmd": 0.0, f"{v}_flow": 0.0}
    return base | over


def vent(ps: float, **over) -> dict:
    p = vented_pressure(ps)
    return steady(pressure=p, purge_valve_pos=100.0, purge_cmd=100.0,
                  purge_flow=0.352 * 100 * math.sqrt(max(p - 100, 0.0))) | over


def window(fn, process_s: float, scale: float = 10.0, poll_wall_s: float = 0.25, quality=lambda ps, tag: "GOOD") -> Window:
    """Sample fn(process_s) -> {tag: value} every poll_wall_s of wall time for process_s process seconds."""
    samples: dict[str, list] = {}
    n = int(process_s / scale / poll_wall_s) + 1
    for i in range(n):
        t = i * poll_wall_s
        ps = t * scale
        for tag, v in fn(ps).items():
            samples.setdefault(tag, []).append((t, v, None, quality(ps, tag)))
    return Window(t0=0.0, t1=(n - 1) * poll_wall_s, process_time_scale=scale, samples=samples, spans=SPANS)
