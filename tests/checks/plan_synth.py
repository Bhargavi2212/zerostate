"""Small hand-built plant maps and plans for the plan-rule tests."""

from zerostate.models.envelope import IsolationPlan
from zerostate.models.plant_map import PlantMap

DEFAULTS = {"hold_test": {"hold_process_s": 600, "window_process_s": 60, "max_rise_kpa": 1.0},
            "vent_target_kpa_abs": 102, "p_depressurised_kpa_abs": 105, "checks": {}}
VALVE = {"kind": "valve", "device": "block_valve", "actuation": "manual", "normal_state": "open"}


def pmap(nodes: dict[str, dict], pipes: str, instruments=()) -> PlantMap:
    """nodes: id -> fields; pipes: "A-B B-C" (ids must not contain '-')."""
    return PlantMap.model_validate({
        "plant": "t", "nodes": [{"id": k, **v} for k, v in nodes.items()],
        "pipes": [dict(zip("ab", p.split("-"), strict=True)) for p in pipes.split()],
        "instruments": list(instruments), "plan_defaults": DEFAULTS})


def plan(work="W", points=(), proving=(), witnesses=(), steps=()) -> IsolationPlan:
    """points: (tag, isolation_type) closed block valves; proving: (tag, proves, discharges_to)."""
    return IsolationPlan.model_validate({
        "plant": "t", "work": {"equipment": work, "task": "test"},
        "points": [{"tag": t, "device": "block_valve", "isolation_type": it, "normal_state": "open",
                    "required_state": "closed", "apply_seq": i, "remove_seq": len(points) - i}
                   for i, (t, it) in enumerate(points, 1)],
        "proving": [{"tag": t, "kind": "bleed", "proves": list(pr), "discharges_to": d} for t, pr, d in proving],
        "witnesses": list(witnesses), "steps": list(steps), "hold_test": DEFAULTS["hold_test"]})


# S -> V1 -> W: one source, one block, the work vessel
LINE = pmap({"S": {"kind": "source", "energy": "process_gas", "hazardous": True}, "V1": VALVE, "W": {"kind": "vessel"}},
            "S-V1 V1-W")
