"""Every import route ends here: the list is saved as a draft (<data>/drafts/<id>.json), merged with the
plant map (graph/build.py) and the plan checks run on it at once. A draft with an unresolved null can't
be confirmed (confirm.py)."""

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from zerostate.models.envelope import IsolationList, IsolationPlan
from zerostate.models.plant_map import PlantMap

DRAFT_ID = re.compile(r"[0-9a-f]{12}")


def put(p: Path, text: str) -> None:
    """Write a local record (draft, confirmation). open().write: the package makes no write_* calls."""
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def save_draft(lst: IsolationList, route: str, source_name: str, data_dir: str | Path,
               transcript: str | None = None) -> dict:
    """`transcript`: the photo route's verbatim reading, shown beside the photo when the person confirms."""
    d = {"id": uuid.uuid4().hex[:12], "route": route, "source_name": source_name,
         "list": lst.model_dump(mode="json"), "transcript": transcript,
         "created": datetime.now(UTC).isoformat(timespec="seconds")}
    out = Path(data_dir) / "drafts"
    out.mkdir(parents=True, exist_ok=True)
    put(out / f"{d['id']}.json", json.dumps(d, indent=2))
    return d


def load_draft(draft_id: str, data_dir: str | Path) -> dict:
    p = Path(data_dir) / "drafts" / f"{draft_id}.json"
    if not DRAFT_ID.fullmatch(draft_id) or not p.exists():
        raise FileNotFoundError(f"no draft {draft_id}")
    return json.loads(p.read_text(encoding="utf-8"))


def unresolved(lst: IsolationList) -> list[str]:
    """Every null that matters: a person resolves each before the draft can be confirmed."""
    out = [] if lst.work_equipment else ["work_equipment is unclear"]
    for i, p in enumerate(lst.points, 1):
        missing = [f for f in ("tag", "required_state", "seq") if getattr(p, f) is None]
        missing += ["isolation_type"] if p.required_state == "closed" and p.isolation_type is None else []
        out += [f"point {i} ({p.tag or '?'}): {f} is unclear" + (f" - {p.note}" if p.note else "") for f in missing]
    out += [f"proving point {i}: tag is unclear" for i, g in enumerate(lst.proving, 1) if g.tag is None]
    return out


def defaults_used(lst: IsolationList, pmap: PlantMap) -> list[dict]:
    """Values the person did not write that the plan takes from the plant: shown and confirmed knowingly."""
    if lst.hold_minutes is not None:
        return []
    return [{"field": "hold_minutes", "value": pmap.plan_defaults.hold_test.hold_process_s / 60, "source": "plant default"}]


def check_draft(draft: dict, pmap: PlantMap, params: dict) -> tuple[IsolationPlan | None, dict]:
    """Merge with the map and run the plan checks. A list with nulls isn't merged: a plan built from
    guesses would not be the person's plan."""
    lst = IsolationList.model_validate(draft["list"])
    todo = unresolved(lst)
    plan, findings = None, []
    if not todo:
        from zerostate.checks.plan import run_plan_checks
        from zerostate.graph.build import merge

        plan, problems = merge(pmap, lst)
        todo += list(problems)
        findings = run_plan_checks(plan, pmap, params) if plan else []
    return plan, {"draft": draft, "plan_hash": plan.content_hash() if plan else None,
                  "findings": [f.model_dump(mode="json") for f in findings], "unresolved": todo,
                  "defaults": defaults_used(lst, pmap)}
