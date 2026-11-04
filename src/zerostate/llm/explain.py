"""P3-4 explain: a plain-language answer about one session, from its logged findings only.

- Muse Spark gets the question, the session's findings (with their ids and messages, which carry the
  evidence numbers), the verdict tracks and the plan's work scope. Temperature 0, JSON reply.
- The answer must cite at least one finding id that exists in the session; an uncited answer is retried
  once, then a fixed fallback quotes the finding's logged message.
- A request to override, approve, pass or unblock gets a fixed reply, with no model call.
- Every answer goes through the never-say check; a hit means the fallback.
- Read only: this module gets plain data and returns text. It has no handle on the audit log, the
  inbox or the session, so an answer can't change a verdict or the log.
"""

import re
from importlib.resources import files
from string import Template

from pydantic import BaseModel

from zerostate import wording
from zerostate.llm.client import spark_json

PROMPT_ID = "explain_v1"
REFUSAL = "I can't change a verdict; only a person signs, and a block stays a block."
MAX_FINDINGS = 400
CHANGE_REQUEST = re.compile(
    r"\b(overrid\w*|overrul\w*|approv\w*|unblock\w*|bypass\w*|waiv\w*|clear (it|this|the block)|lift the block|remove the block"
    r"|mark (it|this|the \w+) (as )?(pass|passed|ok|done)|let (it|this|me) (pass|through|go)"
    r"|(make|let|set) (it|this) pass|pass (it|this|the (job|check|step|session))|change the verdict|sign (it|this|off))\b",
    re.IGNORECASE)
FINDING_ID = re.compile(r"\b\d+:[A-Z]+(?:-[A-Z]+)+\b")


class Answer(BaseModel):
    answer: str
    cites: list[str]


def _verdicts(tracks: dict) -> str:
    out = []
    for name, t in (tracks or {}).items():
        if t:
            out.append(f"{name}: {t.get('verdict')} ({'; '.join(t.get('reasons') or []) or 'no reasons logged'})")
    return " | ".join(out) or "none logged yet"


def _rows(findings: list[dict]) -> str:
    keep = findings if len(findings) <= MAX_FINDINGS else (
        [f for f in findings if f["status"] != "PASS"] + [f for f in findings if f["status"] == "PASS"])[:MAX_FINDINGS]
    return "\n".join(f"{f['id']} | {f['status']} | {f['rule_id']} | {f.get('step')} | {f.get('source')} | {f['message']}"
                     for f in keep) or "(none)"


def fallback(question: str, findings: list[dict]) -> dict:
    """Quote the finding the question names, else the first non-PASS finding, else the first finding."""
    by_id = {f["id"]: f for f in findings}
    named = [by_id[i] for i in FINDING_ID.findall(question) if i in by_id]
    f = (named or [x for x in findings if x["status"] != "PASS"] or findings or [None])[0]
    if f is None:
        return {"answer": "No findings are logged for this session yet.", "cites": []}
    return {"answer": f"The log records finding {f['id']} ({f['rule_id']}, {f['status']}): {f['message']}.", "cites": [f["id"]]}


def explain(question: str, detail: dict, opener=None) -> dict:
    """{answer, cites}. `detail` is the API's SessionDetail (findings with ids, tracks, plan)."""
    findings = detail.get("findings") or []
    if CHANGE_REQUEST.search(question):
        return {"answer": REFUSAL, "cites": []}
    if not findings:
        return fallback(question, findings)
    work = (detail.get("plan") or {}).get("work") or {}
    system = Template((files("zerostate.llm") / "prompts" / f"{PROMPT_ID}.md").read_text(encoding="utf-8")).substitute(
        session=detail.get("id"), equipment=work.get("equipment", "?"), task=work.get("task", "?"),
        verdicts=_verdicts(detail.get("tracks")), findings=_rows(findings))
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": question.strip()[:2000]}]
    ids = {f["id"] for f in findings}
    for _ in (1, 2):
        a = spark_json(msgs, Answer, f"explain:{PROMPT_ID}", opener=opener, temperature=0)
        cites = list(dict.fromkeys(c for c in a.cites if c in ids))
        if wording.hits(a.answer):
            break  # a never-say hit is never shown: the fallback
        if cites:
            return {"answer": a.answer.strip(), "cites": cites}
    return fallback(question, findings)
