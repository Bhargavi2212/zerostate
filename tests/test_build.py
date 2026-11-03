"""graph/build.py: plant map + isolation list -> plan (deterministic, never invents a value)."""

from pathlib import Path

import yaml

from zerostate.graph.build import merge
from zerostate.models.envelope import IsolationList
from zerostate.models.plant_map import PlantMap

P2 = Path(__file__).parents[1] / "plants" / "p2_gasline"


def load(name):
    return yaml.safe_load((P2 / name).read_text(encoding="utf-8"))


MAP = PlantMap.model_validate(load("plant_map.yaml"))
LIST = IsolationList.model_validate(load("isolation_list.yaml"))


def test_merge_is_deterministic():
    a, _ = merge(MAP, LIST)
    b, _ = merge(PlantMap.model_validate(load("plant_map.yaml")), IsolationList.model_validate(load("isolation_list.yaml")))
    assert a.content_hash() == b.content_hash()


def test_p2_plan_steps_and_sides():
    plan, problems = merge(MAP, LIST)
    assert problems == []
    assert [(s.kind, s.target) for s in plan.steps] == [
        ("isolate", "XV-201"), ("isolate", "XV-203"), ("vent_open", "BV-202"), ("isolate", "XV-204"),
        ("vent_open", "VV-213"), ("vent_close", "VV-213"), ("hold", None), ("vent_open", "VV-213"), ("final", None)]
    assert plan.steps[2].checks == MAP.plan_defaults.checks["bleed_open"]
    assert plan.steps[7].checks == MAP.plan_defaults.checks["final_vent"]
    assert [(p.tag, p.apply_seq, p.remove_seq) for p in plan.points] == [("XV-201", 1, 3), ("XV-203", 2, 2), ("XV-204", 4, 1)]
    side = {w.signal_ref: w.side for w in plan.witnesses}
    assert (side["PT-200"], side["PT-202"], side["PT-211"], side["PT-212"]) == ("upstream", "between_blocks", "work", "work")
    assert {p.tag: p.proves for p in plan.proving} == {"BV-202": ("XV-201", "XV-203"), "VV-213": ("XV-204",)}
    assert plan.hold_pressure_kpa_abs == 200


def test_merge_never_invents_a_value():
    d = load("isolation_list.yaml")
    d["hold_minutes"] = 5
    d["points"][1]["isolation_type"] = None
    d["points"][3]["tag"] = "XV-999"
    plan, problems = merge(MAP, IsolationList.model_validate(d))
    assert plan is None
    assert any("hold_minutes 5" in p for p in problems)
    assert any("XV-203: isolation_type is unclear" in p for p in problems)
    assert any("XV-999: not in the plant map" in p for p in problems)
