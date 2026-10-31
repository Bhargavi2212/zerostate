from pathlib import Path

import yaml

from zerostate.adapters.modbus import load_map
from zerostate.models.envelope import IsolationPlan

P1 = Path(__file__).parents[1] / "plants" / "p1_grfics"


def test_p1_map_loads_and_covers_plan_tags():
    m = load_map(P1 / "modbus_map.yaml")
    tags = {e.tag for e in m.tags}
    assert len(tags) == len(m.tags) == 22
    plan = IsolationPlan.model_validate(yaml.safe_load((P1 / "envelope.yaml").read_text()))
    used = {p.tag for p in plan.points} | {p.tag for p in plan.proving} | {w.signal_ref for w in plan.witnesses}
    used |= {s for r in plan.relations for s in r.signals}
    assert used <= tags, used - tags
