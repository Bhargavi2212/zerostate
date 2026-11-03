"""Typed text -> Muse Spark (strict JSON) -> IsolationList draft. The model only structures what the
person wrote; a person confirms the result (confirm.py).

Code guard on top of the prompt: a tag that does not appear in the author's text is not kept. It is
set to null with a note, which blocks confirmation until a person resolves it.
"""

import re
from importlib.resources import files
from string import Template

from zerostate.llm.client import spark_json
from zerostate.models.envelope import IsolationList
from zerostate.models.plant_map import PlantMap

PROMPT_ID = "import_list_v1"


def system_prompt(pmap: PlantMap) -> str:
    text = (files("zerostate.llm") / "prompts" / f"{PROMPT_ID}.md").read_text(encoding="utf-8")
    return Template(text).substitute(plant=pmap.plant, tags=", ".join(sorted(pmap.tags())))


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _keep_written_tags(lst: IsolationList, text: str) -> IsolationList:
    seen = _norm(text)

    def unwritten(tag):
        return tag is not None and _norm(tag) not in seen

    def drop(x):
        return x.model_copy(update={"tag": None}) if unwritten(x.tag) else x

    points = tuple(p.model_copy(update={"tag": None, "note": f"tag {p.tag} is not in the text"}) if unwritten(p.tag) else p
                   for p in lst.points)
    dropped = [f"{name} {v} is not in the text" for name, v in
               [("work equipment", lst.work_equipment), ("vent", lst.vent), *(("proving point", g.tag) for g in lst.proving)]
               if unwritten(v)]
    return lst.model_copy(update={
        "points": points, "proving": tuple(drop(g) for g in lst.proving), "notes": lst.notes + tuple(dropped),
        "work_equipment": None if unwritten(lst.work_equipment) else lst.work_equipment,
        "vent": None if unwritten(lst.vent) else lst.vent})


def import_text(text: str, pmap: PlantMap, opener=None) -> IsolationList:
    msgs = [{"role": "system", "content": system_prompt(pmap)}, {"role": "user", "content": text}]
    lst = spark_json(msgs, IsolationList, f"import_text:{PROMPT_ID}", opener=opener)
    return _keep_written_tags(lst.model_copy(update={"plant": pmap.plant}), text)
