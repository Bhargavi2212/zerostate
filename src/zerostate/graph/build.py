"""Plant map -> graph, and plant map + isolation list -> IsolationPlan.

merge() is deterministic (same inputs, same plan hash) and never invents a value: anything the list
leaves unclear (None), a tag the map lacks, a field the map leaves empty, or a hold time different from
the plant's fixed hold comes back as a problem, and no plan is built. The importer marks those as
nulls the person must resolve.
"""

from typing import get_args

import networkx as nx

from zerostate.graph.regions import sides
from zerostate.models.envelope import (
    EnergySource,
    IsolationList,
    IsolationPlan,
    IsolationPoint,
    ProvingPoint,
    Step,
    Witness,
    WorkScope,
)
from zerostate.models.plant_map import PlantMap

DEVICES = get_args(IsolationPoint.model_fields["device"].annotation)
PROVING_KIND = {"vent": "vent", "bleed": "bleed"}  # any other node proves as a test point


def graph(m: PlantMap) -> nx.Graph:
    """Nodes = map nodes (attribute `node` = the map Node), edges = pipes, plus vent -> header edges."""
    g = nx.Graph()
    for n in m.nodes:
        g.add_node(n.id, node=n)
    for p in m.pipes:
        g.add_edge(p.a, p.b)
    for n in m.nodes:
        if n.discharges_to and n.discharges_to.startswith("header:"):
            g.add_edge(n.id, n.discharges_to.split(":", 1)[1])
    return g


def _problems(m: PlantMap, lst: IsolationList) -> list[str]:
    d, out = m.plan_defaults, []
    if lst.plant != m.plant:
        out.append(f"list is for {lst.plant}, map is {m.plant}")
    if lst.work_equipment is None:
        out.append("work_equipment is unclear")
    if lst.vent is None:
        out.append("vent is unclear")
    # not written = the plant's fixed hold applies (a CSV export has no hold column); a different value is a conflict
    if lst.hold_minutes is not None and lst.hold_minutes * 60 != d.hold_test.hold_process_s:
        out.append(f"hold_minutes {lst.hold_minutes} must equal the plant's fixed hold "
                   f"({d.hold_test.hold_process_s / 60:g} min)")
    seqs = [p.seq for p in lst.points if p.seq is not None]
    if len(seqs) != len(set(seqs)):
        out.append("seq values repeat")
    for i, p in enumerate(lst.points, 1):
        name = p.tag or f"point {i}"
        out += [f"{name}: {f} is unclear" for f in ("tag", "required_state", "seq") if getattr(p, f) is None]
        n = m.node(p.tag) if p.tag else None
        if p.tag and n is None:
            out.append(f"{p.tag}: not in the plant map")
        elif n and p.required_state == "closed":
            if p.isolation_type is None:
                out.append(f"{p.tag}: isolation_type is unclear")
            if n.device not in DEVICES:
                out.append(f"{p.tag}: map device {n.device} can't be an isolation point")
            if n.normal_state is None:
                out.append(f"{p.tag}: map has no normal_state")
        elif n and p.required_state == "open" and n.kind not in PROVING_KIND:
            out.append(f"{p.tag}: only a vent or bleed may be listed open")
    if any(pr.tag is None for pr in lst.proving):
        out.append("a proving point tag is unclear")
    for t in [pr.tag for pr in lst.proving if pr.tag] + ([lst.vent] if lst.vent else []):
        if m.node(t) is None:
            out.append(f"{t}: not in the plant map")
        elif m.node(t).discharges_to is None:
            out.append(f"{t}: map has no discharges_to")
    roles = {"vent_open", "vent_close", "hold"} | ({"final_vent"} if d.hold_pressure_kpa_abs is not None else set())
    roles |= {"isolate" if p.required_state == "closed" else "bleed_open" for p in lst.points}
    out += [f"plan_defaults has no checks for {r}" for r in sorted(roles - set(d.checks))]
    out += [f"source {n.id}: map has no energy" for n in m.nodes if n.kind == "source" and n.energy is None]
    return out


def merge(m: PlantMap, lst: IsolationList) -> tuple[IsolationPlan | None, list[str]]:
    """(plan, []) or (None, problems)."""
    problems = _problems(m, lst)
    if problems:
        return None, problems
    d = m.plan_defaults
    pts = sorted(lst.points, key=lambda p: p.seq)
    closed = [p for p in pts if p.required_state == "closed"]
    points = tuple(IsolationPoint(tag=p.tag, device=m.node(p.tag).device, isolation_type=p.isolation_type,
                                  normal_state=m.node(p.tag).normal_state, required_state="closed",
                                  apply_seq=p.seq, remove_seq=len(closed) - i, lock_id=p.lock_id)
                   for i, p in enumerate(closed))
    proves = {pr.tag: pr.proves for pr in lst.proving}
    ptags = dict.fromkeys([p.tag for p in pts if p.required_state == "open"] + [lst.vent] + list(proves))
    proving = tuple(ProvingPoint(tag=t, kind=PROVING_KIND.get(m.node(t).kind, "test_point"),
                                 proves=tuple(proves.get(t, ())), discharges_to=m.node(t).discharges_to)
                    for t in ptags)

    steps: list[Step] = []

    def add(kind, role=None, target=None, req=None, settle=d.settle_process_s):
        steps.append(Step(k=len(steps) + 1, kind=kind, target=target, required_state=req,
                          checks=d.checks[role] if role else (), settle_process_s=settle))

    for p in pts:
        if p.required_state == "closed":
            add("isolate", "isolate", p.tag, 0)
        else:
            add("vent_open", "bleed_open", p.tag, 100)
    add("vent_open", "vent_open", lst.vent, 100)  # to the hold pressure, or the full vent
    add("vent_close", "vent_close", lst.vent, 0)
    add("hold", "hold", settle=0)
    if d.hold_pressure_kpa_abs is not None:
        add("vent_open", "final_vent", lst.vent, 100)  # final vent; the vent stays open for the work
    add("final", settle=0)

    side = sides(graph(m), {p.tag for p in closed}, lst.work_equipment)
    witnesses = tuple(Witness(segment=i.at, signal_ref=i.signal_ref, role=i.role, side=side[i.at], point=i.point)
                      for i in m.instruments)
    plan = IsolationPlan(
        plant=m.plant, work=WorkScope(equipment=lst.work_equipment, task=""),
        sources=tuple(EnergySource(tag=n.id, type=n.energy, max_magnitude=n.pressure_kpa_abs)
                      for n in m.nodes if n.kind == "source"),
        points=points, proving=proving, witnesses=witnesses, relations=d.relations, assumptions=d.assumptions,
        hold_test=d.hold_test, steps=tuple(steps), vent_target_kpa_abs=d.vent_target_kpa_abs,
        p_depressurised_kpa_abs=d.p_depressurised_kpa_abs, hold_pressure_kpa_abs=d.hold_pressure_kpa_abs,
        camera=d.camera)
    return plan, []
