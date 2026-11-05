"""A worker's request ("check my isolation on ...") -> one of the plans a person confirmed, or none.

Muse Spark only matches words to a plan id from the list it is given (temperature 0, JSON reply). Code
checks the id against that list: an id that is not on it counts as none. Nothing here starts a session,
confirms or signs; the API endpoint that calls it is read-only.
"""

from importlib.resources import files
from string import Template

from pydantic import BaseModel

from zerostate import wording
from zerostate.llm.client import spark_json

PROMPT_ID = "resolve_request_v2"  # v2 (Nov 4 rehearsal): naming the equipment is enough; v1 also wanted the task words


class Pick(BaseModel):
    plan_id: str | None
    reason: str = ""


def prompt(plans: list[dict]) -> str:
    rows = "\n".join(f"- {p['id']}: {p['plant']}, {p['equipment']}, {p['task']}" for p in plans) or "(none)"
    return Template((files("zerostate.llm") / "prompts" / f"{PROMPT_ID}.md").read_text(encoding="utf-8")).substitute(plans=rows)


def resolve(text: str, plans: list[dict], opener=None) -> dict:
    """{plan_id: an id from `plans` or None, reason}. No plans or an empty request: no model call."""
    if not plans or not text.strip():
        return {"plan_id": None, "reason": "no confirmed plans" if not plans else "empty request"}
    msgs = [{"role": "system", "content": prompt(plans)}, {"role": "user", "content": text.strip()[:2000]}]
    pick = spark_json(msgs, Pick, f"resolve:{PROMPT_ID}", opener=opener, temperature=0)
    ids = {p["id"] for p in plans}
    reason = pick.reason.strip() if not wording.hits(pick.reason) else ""
    if pick.plan_id not in ids:  # a made-up id is none
        return {"plan_id": None, "reason": reason if pick.plan_id is None else "the model named a plan that is not on the list"}
    return {"plan_id": pick.plan_id, "reason": reason}
