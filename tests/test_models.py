from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from zerostate.models.envelope import IsolationPlan, SessionState, Signature
from zerostate.models.verdict import Verdict

STUB = Path(__file__).parents[1] / "plants" / "p1_grfics" / "envelope.yaml"


def load_stub() -> IsolationPlan:
    return IsolationPlan.model_validate(yaml.safe_load(STUB.read_text()))


def test_verdict_has_no_safe():
    assert not [v for v in Verdict if "SAFE" in v.name or "SAFE" in v.value]


def test_unknown_field_rejected():
    data = yaml.safe_load(STUB.read_text())
    data["hold_test"]["surprise"] = 1
    with pytest.raises(ValidationError):
        IsolationPlan.model_validate(data)


def test_hash_stable_through_yaml_roundtrip():
    plan = load_stub()
    again = IsolationPlan.model_validate(yaml.safe_load(yaml.safe_dump(plan.model_dump(mode="json"))))
    assert again.content_hash() == plan.content_hash()


def test_hash_changes_when_plan_changes():
    plan = load_stub()
    changed = plan.model_copy(update={"hold_test": plan.hold_test.model_copy(update={"max_rise_kpa": 11})})
    assert changed.content_hash() != plan.content_hash()


def test_plan_is_immutable():
    plan = load_stub()
    with pytest.raises(ValidationError):
        plan.plant = "other"
    with pytest.raises(AttributeError):
        plan.points.append(plan.points[0])


def test_session_edits_do_not_touch_plan_hash():
    plan = load_stub()
    h = plan.content_hash()
    session = SessionState(plan_hash=h)
    session.point_status["f1"] = "ITG"
    session.signatures.append(Signature(role="installer", person="a", ts=datetime.now(UTC)))
    assert plan.content_hash() == h == session.plan_hash


def test_plan_steps_name_their_checks():
    plan = load_stub()
    assert [st.k for st in plan.steps] == list(range(1, 9))
    assert all(c.startswith("LIVE-") for st in plan.steps for c in st.checks)
    assert plan.vent_target_kpa_abs < plan.p_depressurised_kpa_abs
