from pathlib import Path

import pytest
import yaml

from zerostate.adapters.modbus import load_map
from zerostate.models.envelope import IsolationList, IsolationPlan, step_targets
from zerostate.models.plant_map import PlantMap

P1 = Path(__file__).parents[1] / "plants" / "p1_grfics"
P2 = Path(__file__).parents[1] / "plants" / "p2_gasline"


def test_p1_map_loads_and_covers_plan_tags():
    m = load_map(P1 / "modbus_map.yaml")
    tags = {e.tag for e in m.tags}
    assert len(tags) == len(m.tags) == 22
    plan = IsolationPlan.model_validate(yaml.safe_load((P1 / "envelope.yaml").read_text()))
    used = {w.signal_ref for w in plan.witnesses} | {s for r in plan.relations for s in r.signals}
    used |= {st.target for st in plan.steps if st.kind == "mode"}
    assert used <= tags, used - tags
    points = {p.tag for p in plan.points} | {p.tag for p in plan.proving}
    assert {w.point for w in plan.witnesses if w.point} <= points
    assert {t for st in plan.steps if st.kind in ("isolate", "vent_open", "vent_close") for t in step_targets(st)} <= points


# ---------------------------------------------------------------- Phase 2: plant graphs


def load(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("plant", [P1, P2])
def test_plant_graph_loads_and_is_connected(plant):
    m = PlantMap.model_validate(load(plant / "plant_map.yaml"))
    linked = {p.a for p in m.pipes} | {p.b for p in m.pipes}
    assert {n.id for n in m.nodes} <= linked  # no orphan node


def test_p1_graph_covers_the_live_plan():
    m = PlantMap.model_validate(load(P1 / "plant_map.yaml"))
    plan = IsolationPlan.model_validate(load(P1 / "envelope.yaml"))
    assert {p.tag for p in plan.points} | {p.tag for p in plan.proving} <= {n.id for n in m.nodes}
    assert {w.signal_ref for w in plan.witnesses} <= {i.signal_ref for i in m.instruments}
    assert plan.work.equipment in {n.id for n in m.nodes}


def test_p2_list_names_only_map_tags():
    m = PlantMap.model_validate(load(P2 / "plant_map.yaml"))
    lst = IsolationList.model_validate(load(P2 / "isolation_list.yaml"))
    named = {p.tag for p in lst.points} | {p.tag for p in lst.proving} | {t for p in lst.proving for t in p.proves}
    assert named | {lst.vent, lst.work_equipment} <= m.tags()
    assert m.plan_defaults.hold_test.hold_process_s == lst.hold_minutes * 60  # the plant's fixed hold


def test_map_rejects_unknown_nodes():
    bad = load(P2 / "plant_map.yaml")
    bad["pipes"].append({"a": "F-210", "b": "XV-999"})
    with pytest.raises(ValueError, match="unknown nodes"):
        PlantMap.model_validate(bad)
