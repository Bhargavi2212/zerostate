"""graph/build.py: plant map + isolation list -> plan (deterministic, never invents a value); the plan
checks on the real P1 and P2 plans; the plan check at session start and its replay."""

from pathlib import Path

import pytest
import yaml
from checks.synth import PARAMS
from test_session import Driver, clean_run

from zerostate.audit.replay import replay
from zerostate.checks.plan import PLAN_RULES, run_plan_checks
from zerostate.graph.build import merge
from zerostate.models.envelope import IsolationList, IsolationPlan
from zerostate.models.plant_map import PlantMap
from zerostate.session import PlanCheckFailed

P1 = Path(__file__).parents[1] / "plants" / "p1_grfics"
P2 = Path(__file__).parents[1] / "plants" / "p2_gasline"
P1_MAP = PlantMap.model_validate(yaml.safe_load((P1 / "plant_map.yaml").read_text(encoding="utf-8")))
OVERRIDE = "control-valve isolation accepted for live-evidence testbed"


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


def failed(findings):
    return {f.rule_id for f in findings if f.status != "PASS"}


def test_correct_p2_plan_passes_every_plan_rule():
    plan, _ = merge(MAP, LIST)
    findings = run_plan_checks(plan, MAP, PARAMS)
    assert [f.rule_id for f in findings] == list(PLAN_RULES) and failed(findings) == set()


def test_p1_live_plan_is_blocked_by_software_and_type_only():
    plan = IsolationPlan.model_validate(yaml.safe_load((P1 / "envelope.yaml").read_text(encoding="utf-8")))
    assert failed(run_plan_checks(plan, P1_MAP, PARAMS)) == {"PLAN-SOFTWARE", "PLAN-TYPE"}


def test_session_refuses_a_plan_fail_without_override(tmp_path):
    with pytest.raises(PlanCheckFailed, match="PLAN-SOFTWARE"):
        Driver(tmp_path, plant_map=P1_MAP)


def test_session_with_override_logs_stamps_and_replays(tmp_path):
    d = Driver(tmp_path, plant_map=P1_MAP, override=OVERRIDE)
    clean_run(d)
    events = d.log.events("s1")
    assert events[0]["payload"]["plan_check_override"] == OVERRIDE
    ev = events[1]["payload"]
    assert ev["source"] == "plan" and ev["map_hash"] == P1_MAP.content_hash() and ev["override"] == OVERRIDE
    assert failed_logged(ev) == {"PLAN-SOFTWARE", "PLAN-TYPE"}
    st = d.status()
    assert st["verdict"] == "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"  # the override never changes a verdict
    assert all(e["payload"]["plan_check_override"] == OVERRIDE for e in events if e["kind"] == "verdict")
    assert replay(d.log, "s1", PARAMS) == []


def failed_logged(ev):
    return {f["rule_id"] for f in ev["findings"] if f["status"] != "PASS"}


def test_replay_reports_a_changed_plan_finding(tmp_path):
    d = Driver(tmp_path, plant_map=P1_MAP, override=OVERRIDE)
    ev = d.log.events("s1")[1]
    payload = ev["payload"] | {"findings": [f | {"status": "PASS"} for f in ev["payload"]["findings"]]}
    d.log.append("s2", "session_start", d.log.events("s1")[0]["payload"])
    d.log.append("s2", "evaluation", payload)
    assert any("(plan)" in m for m in replay(d.log, "s2", PARAMS))


def test_merged_p2_plan_has_the_steps_the_p2_rules_were_tested_on():
    """graph/build.py (P2-2) and the P2 rule tests (checks/synth_p2.py, P2-6) must describe one plan."""
    from checks.synth_p2 import PLAN

    m = PlantMap.model_validate(yaml.safe_load((P2 / "plant_map.yaml").read_text(encoding="utf-8")))
    lst = IsolationList.model_validate(yaml.safe_load((P2 / "isolation_list.yaml").read_text(encoding="utf-8")))
    plan, problems = merge(m, lst)
    assert problems == []
    assert [s.model_dump() for s in plan.steps] == [s.model_dump() for s in PLAN.steps]
