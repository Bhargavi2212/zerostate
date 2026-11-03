"""Plant map: the plant as a graph (data), plus the plan defaults a merged plan takes from the plant.

A plan is the plant map plus an isolation list a person authors (models/envelope.IsolationList);
graph/build.py merges the two. Instruments are not graph nodes: each sits `at` a node.
"""

from typing import Literal

from pydantic import model_validator

from zerostate.models.envelope import Assumption, HoldTest, Relation, _Plan

NodeKind = Literal["source", "vessel", "segment", "header", "valve", "vent", "bleed", "relief", "heater"]
PATH_KINDS = ("valve", "vent", "bleed", "relief")  # nodes that open or close a path


class Node(_Plan):
    id: str
    kind: NodeKind
    # source: an energy source at the boundary of the plant
    energy: str | None = None  # e.g. process_gas, process_liquid, nitrogen
    pressure_kpa_abs: float | None = None
    hazardous: bool = False
    # valve / vent / bleed / relief
    device: Literal["block_valve", "control_valve", "check_valve", "relief_valve"] | None = None
    actuation: Literal["manual", "actuated"] | None = None
    normal_state: Literal["open", "closed"] | None = None
    discharges_to: str | None = None  # atmosphere | flare | header:<node id> (vent, bleed, relief)


class Instrument(_Plan):
    tag: str  # the plant tag (PT-211)
    signal_ref: str  # the adapter tag it is read as
    role: str  # pressure | level | flow | feedback | command | mode
    at: str  # node it measures; a witness's side is computed from this, never declared per job
    point: str | None = None  # valve it belongs to (feedback / command / flow)


class Pipe(_Plan):
    a: str
    b: str


class PlanDefaults(_Plan):
    """What a merged plan takes from the plant, not from the person's list. Fixed per plant before sealing."""

    hold_test: HoldTest
    vent_target_kpa_abs: float
    p_depressurised_kpa_abs: float
    hold_pressure_kpa_abs: float | None = None  # hold at residual pressure (P2); None = hold after the full vent
    settle_process_s: float = 60
    camera: Literal["optional", "required"] | None = None
    checks: dict[str, tuple[str, ...]]  # step role -> rule ids (isolate, bleed_open, vent_open, vent_close, hold, final_vent)
    relations: tuple[Relation, ...] = ()
    assumptions: tuple[Assumption, ...] = ()


class PlantMap(_Plan):
    plant: str
    nodes: tuple[Node, ...]
    pipes: tuple[Pipe, ...]
    instruments: tuple[Instrument, ...] = ()
    plan_defaults: PlanDefaults

    @model_validator(mode="after")
    def _consistent(self):
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate node ids: {sorted({i for i in ids if ids.count(i) > 1})}")
        known = set(ids)
        bad = [f"{p.a}-{p.b}" for p in self.pipes if p.a not in known or p.b not in known]
        bad += [f"{i.tag} at {i.at}" for i in self.instruments if i.at not in known]
        bad += [f"{i.tag} point {i.point}" for i in self.instruments if i.point and i.point not in known]
        bad += [f"{n.id} -> {n.discharges_to}" for n in self.nodes if n.discharges_to and n.discharges_to.startswith("header:")
                and n.discharges_to.split(":", 1)[1] not in known]
        if bad:
            raise ValueError(f"map refers to unknown nodes: {bad}")
        return self

    def node(self, node_id: str) -> Node | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def tags(self) -> set[str]:
        """Every name a person may write in an isolation list: nodes and instrument tags."""
        return {n.id for n in self.nodes} | {i.tag for i in self.instruments}
