"""Synthetic P2 windows for rule tests: P2's plan (as graph/build.py would merge map + list), its
provisional thresholds, and windows sampled from P2's own model at 4 Hz wall and x30."""

import importlib.util
from pathlib import Path

import yaml

from zerostate.adapters.opcua import load_map
from zerostate.config import load_thresholds
from zerostate.models.envelope import IsolationPlan
from zerostate.models.evidence import Window

P2 = Path(__file__).parents[2] / "plants" / "p2_gasline"
spec = importlib.util.spec_from_file_location("p2_model_synth", P2 / "model.py")
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)

PARAMS = load_thresholds(P2 / "thresholds.yaml")
SPANS = {e.tag: (e.scale_min, e.scale_max) for e in load_map(P2 / "opcua_map.yaml").tags}
SCALE, POLL_WALL_S = 30.0, 0.25
_D = yaml.safe_load((P2 / "plant_map.yaml").read_text(encoding="utf-8"))["plan_defaults"]
VALVES = ("XV-201", "BV-202", "XV-203", "VV-213", "XV-204")


def _w(seg, ref, role, side, point=None):
    return {"segment": seg, "signal_ref": ref, "role": role, "side": side, "point": point}


def _step(k, kind, target, req, role):
    return {"k": k, "kind": kind, "target": target, "required_state": req, "checks": _D["checks"][role],
            "settle_process_s": _D["settle_process_s"]}


PLAN = IsolationPlan.model_validate({
    "plant": "p2_gasline", "work": {"equipment": "F-210", "task": "filter change"},
    "sources": [{"tag": "S-200", "type": "nitrogen"}, {"tag": "D-220", "type": "nitrogen"}],
    "points": [{"tag": t, "device": "block_valve", "isolation_type": "proved", "normal_state": "open",
                "required_state": "closed", "apply_seq": i, "remove_seq": 4 - i}
               for i, t in enumerate(("XV-201", "XV-203", "XV-204"), 1)],
    "proving": [{"tag": "BV-202", "kind": "bleed", "proves": ["XV-201", "XV-203"], "discharges_to": "atmosphere"},
                {"tag": "VV-213", "kind": "vent", "proves": ["XV-204"], "discharges_to": "atmosphere"}],
    "segments": [{"id": "supply", "members": ["S-200"], "bounded_by": ["XV-201"]},
                 {"id": "cavity", "members": ["C-202"], "bounded_by": ["XV-201", "XV-203", "BV-202"], "vents": ["BV-202"]},
                 {"id": "work", "members": ["F-210"], "bounded_by": ["XV-203", "XV-204", "VV-213", "PSV-214"], "vents": ["VV-213"]}],
    "witnesses": [_w("supply", "PT-200", "pressure", "upstream"), _w("cavity", "PT-202", "pressure", "between_blocks"),
                  _w("work", "PT-211", "pressure", "work"), _w("work", "PT-212", "pressure", "work"),
                  _w("work", "FT-213", "flow", "work", "VV-213")]
                 + [_w("work", f"{v}.{s}", role, "work", v) for v in VALVES for s, role in (("FB", "feedback"), ("CMD", "command"))],
    "relations": _D["relations"], "hold_test": _D["hold_test"],
    "vent_target_kpa_abs": _D["vent_target_kpa_abs"], "p_depressurised_kpa_abs": _D["p_depressurised_kpa_abs"],
    "hold_pressure_kpa_abs": _D["hold_pressure_kpa_abs"],
    "steps": [_step(1, "isolate", "XV-201", 0, "isolate"), _step(2, "isolate", "XV-203", 0, "isolate"),
              _step(3, "vent_open", "BV-202", 100, "bleed_open"), _step(4, "isolate", "XV-204", 0, "isolate"),
              _step(5, "vent_open", "VV-213", 100, "vent_open"), _step(6, "vent_close", "VV-213", 0, "vent_close"),
              {"k": 7, "kind": "hold", "checks": _D["checks"]["hold"]},
              _step(8, "vent_open", "VV-213", 100, "final_vent"), {"k": 9, "kind": "final"}],
})
STEP = {s.k: s for s in PLAN.steps}
BLEED, VENT, HOLD, FINAL_VENT = 3, 5, 7, 8


def line(seed=0, **faults):
    """The plant with faults set from the start (model.GasLine.set keys)."""
    m = model.GasLine(seed=seed)
    for k, v in faults.items():
        m.set(k, v)
    return m


def do(m, *moves, settle=30.0):
    for v, x in moves:
        m.command(v, x)
    m.step(settle)
    return m


def isolated(m):
    """Steps 1-4 done: blocks closed, cavity bled, F-210 at D-220's pressure."""
    return do(m, ("XV-201", 0), ("XV-203", 0), ("BV-202", 100), ("XV-204", 0), settle=60)


def at_hold(m):
    """Steps 5-6 done: vented to the hold pressure, vent closed and settled."""
    m.command("VV-213", 100)
    while m.p("F-210") > PLAN.hold_pressure_kpa_abs:
        m.step(1.5)
    return do(m, ("VV-213", 0))


def window(m, process_s, during=None) -> Window:
    """Sample the model every POLL_WALL_S wall s for process_s process-s; during(m, ps) may change it on the way."""
    samples: dict[str, list] = {}
    n = int(process_s / SCALE / POLL_WALL_S) + 1
    for i in range(n):
        if i:
            m.step(SCALE * POLL_WALL_S)
        if during:
            during(m, i * SCALE * POLL_WALL_S)
        for name, v in m.measure().items():
            tag = name.removesuffix(".PV")
            if tag in SPANS:
                samples.setdefault(tag, []).append((i * POLL_WALL_S, v, None, "GOOD"))
    return Window(t0=0.0, t1=(n - 1) * POLL_WALL_S, process_time_scale=SCALE, samples=samples, spans=SPANS)


def opened(m, valve, process_s):
    """Window from the mark of a step that opens `valve` (commanded at the mark)."""
    m.command(valve, 100)
    return window(m, process_s)
