"""A person confirms a plan; only then can a session start on it.

- A plan file (YAML): the record goes into confirmed.yaml next to it (plants/<p>/confirmed.yaml).
- An importer draft id: the merged plan and the record go to <data>/plans/<hash>.json; refused while
  the draft has anything unresolved.

Run by the owner only. Agents and the eval runner never confirm (CLAUDE.md).
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

from zerostate.importers.draft import check_draft, load_draft, put
from zerostate.models.envelope import IsolationPlan
from zerostate.models.plant_map import PlantMap

ROLES = ("issuer",)
HASH = re.compile(r"[0-9a-f]{64}")


class NotConfirmable(ValueError):
    pass


def _read_yaml(p: Path):
    return yaml.safe_load(p.read_text(encoding="utf-8-sig"))


def _record(plan: IsolationPlan, by: str, role: str) -> dict:
    return {"plan_hash": plan.content_hash(), "by": by, "role": role, "date": datetime.now(UTC).isoformat(timespec="seconds")}


def confirm(target: str, by: str, role: str = "issuer", *, data_dir: str | Path, config_dir: str | Path = "/app/config",
            map_path: str | Path | None = None, params: dict | None = None) -> dict:
    if role not in ROLES or not by.strip():
        raise NotConfirmable(f"a confirmation needs a person's name and a role in {ROLES}")
    p = Path(target)
    if p.suffix in (".yaml", ".yml"):
        plan = IsolationPlan.model_validate(_read_yaml(p))
        rec = _record(plan, by, role)
        book = p.parent / "confirmed.yaml"
        records = (_read_yaml(book) or []) if book.exists() else []
        put(book, yaml.safe_dump([*records, rec], sort_keys=False))
        return rec
    draft = load_draft(target, data_dir)
    plant = draft["list"]["plant"]
    pmap = PlantMap.model_validate(_read_yaml(Path(map_path or Path(config_dir) / plant / "plant_map.yaml")))
    plan, view = check_draft(draft, pmap, params or {})
    if view["unresolved"] or plan is None:
        raise NotConfirmable(f"draft {target} has unresolved items: {view['unresolved']}")
    rec = {**_record(plan, by, role), "defaults": view["defaults"]}  # confirmed knowingly, not silently
    out = Path(data_dir) / "plans" / f"{rec['plan_hash']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    records = json.loads(out.read_text(encoding="utf-8"))["confirmed"] if out.exists() else []
    put(out, json.dumps({"plan": plan.model_dump(mode="json"), "draft": target, "confirmed": [*records, rec]}, indent=2))
    return rec


def is_confirmed(plan_hash: str, config_dirs, data_dir: str | Path) -> dict | None:
    """The latest confirmation record for this plan hash, or None."""
    for d in config_dirs:
        book = Path(d) / "confirmed.yaml"
        if book.exists():
            match = [r for r in (_read_yaml(book) or []) if r.get("plan_hash") == plan_hash]
            if match:
                return match[-1]
    p = Path(data_dir) / "plans" / f"{plan_hash}.json"
    if HASH.fullmatch(plan_hash) and p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        if IsolationPlan.model_validate(d["plan"]).content_hash() == plan_hash and d["confirmed"]:
            return d["confirmed"][-1]
    return None
