"""Isolation plan (frozen, hashed once a person confirms it) and session state (changes during the job)."""

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


class _Plan(BaseModel):
    # Tuples, not lists: a frozen model holding a list can still be mutated in place.
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkScope(_Plan):
    equipment: str
    task: str
    permit_ids: tuple[str, ...] = ()


class EnergySource(_Plan):
    tag: str
    type: str
    max_magnitude: float | None = None


class IsolationPoint(_Plan):
    tag: str
    device: Literal["block_valve", "control_valve", "blind", "spade", "spool_removed", "breaker"]
    isolation_type: Literal["positive", "proved", "non_proved"]
    normal_state: str
    required_state: str
    apply_seq: int
    remove_seq: int
    lock_id: str | None = None
    tag_id: str | None = None


class ProvingPoint(_Plan):
    tag: str
    kind: Literal["vent", "bleed", "drain", "test_point"]
    proves: tuple[str, ...]
    discharges_to: str


class Segment(_Plan):
    id: str
    members: tuple[str, ...]
    bounded_by: tuple[str, ...]
    vents: tuple[str, ...] = ()


class Witness(_Plan):
    segment: str
    signal_ref: str
    role: str  # pressure | level | feedback | command | flow | mode
    side: Literal["work", "upstream", "between_blocks"]
    redundancy_group: str | None = None
    point: str | None = None  # isolation point this witness belongs to (feedback/command/flow)


class Relation(_Plan):
    type: str
    signals: tuple[str, ...]
    params: tuple[tuple[str, float], ...] = ()

    @field_validator("params", mode="before")
    @classmethod
    def _mapping_to_pairs(cls, v):
        return tuple(sorted(v.items())) if isinstance(v, dict) else v


class Assumption(_Plan):
    text: str
    scope: str


class HoldTest(_Plan):
    hold_process_s: float
    window_process_s: float
    max_rise_kpa: float
    upstream_min: float | None = None


class Step(_Plan):
    """One plan step; the rule ids it runs are data, not code."""

    k: int
    kind: Literal["mode", "isolate", "vent_open", "vent_close", "hold", "final"]
    target: str | None = None  # isolation point id, or a tag (e.g. manual_mode)
    required_state: float | None = None
    checks: tuple[str, ...] = ()
    settle_process_s: float = 0
    timeout_process_s: float | None = None


class IsolationPlan(_Plan):
    plant: str
    work: WorkScope
    sources: tuple[EnergySource, ...] = ()
    points: tuple[IsolationPoint, ...] = ()
    proving: tuple[ProvingPoint, ...] = ()
    segments: tuple[Segment, ...] = ()
    witnesses: tuple[Witness, ...] = ()
    relations: tuple[Relation, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    hold_test: HoldTest
    steps: tuple[Step, ...] = ()
    vent_target_kpa_abs: float | None = None  # operator goal (rolling mean)
    p_depressurised_kpa_abs: float | None = None  # acceptance limit LIVE-HOLD checks

    def content_hash(self) -> str:
        canon = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode()).hexdigest()


class Signature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["planner", "approver", "installer", "verifier", "prover", "receiver"]
    person: str
    ts: datetime


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_hash: str
    point_status: dict[str, Literal["ITG", "ETG", "ETUG", "EUG"]] = {}
    signatures: list[Signature] = []
    step_log: list[dict[str, Any]] = []
