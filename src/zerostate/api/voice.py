"""Voice and typed step commands: words -> intent and a read-back. Pure text in, text out; it marks,
verifies, reopens and signs nothing (the console marks a step only after the person confirms the read-back).
Used by the API's /api/voice/command and by the static site's model function."""

import itertools
import re

NDF = "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"

NUMBERS = {w: str(i) for i, w in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                                            "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
                                            "seventeen", "eighteen", "nineteen", "twenty"])}
WORDS = {"confirm": {"yes", "confirm", "confirmed", "correct", "affirmative"},
         "cancel": {"no", "cancel", "negative", "abort"},
         "repeat": {"repeat", "again", "pardon"},
         "status": {"status", "progress"}}
NOT_BY_VOICE = {"sign", "signoff", "signature", "verify", "verified", "reopen", "approve", "override", "accept"}
STATE_WORDS = {"closed": {"closed", "close", "shut"}, "open": {"open", "opened"}}


def _undouble(t: str) -> str:
    """A word the transcriber ran together with itself ("confirmconfirm") is that word once. Exact halves
    only: nothing else is rewritten. Added after voice run 3, unmeasured (eval/results/voice_runs.md)."""
    h = len(t) // 2
    return t[:h] if len(t) % 2 == 0 and h >= 2 and t[:h] == t[h:] else t


def _tokens(text: str) -> list[str]:
    return [NUMBERS.get(t, t) for t in (_undouble(w) for w in re.findall(r"[a-z0-9]+", text.lower()))]


def _norm(target: str) -> str:
    return re.sub(r"[^a-z0-9]", "", target.lower())


def _step_words(s: dict) -> tuple[list[str], str | None]:
    targets = list(s.get("targets") or ([s["target"]] if s.get("target") else []))
    rs = s.get("required_state")
    state = None if rs is None or s["kind"] == "mode" else "closed" if rs <= 5 else "open" if rs >= 95 else None
    return targets, state


def _step_text(s: dict) -> str:
    targets, state = _step_words(s)
    what = " and ".join(targets) or s["kind"].replace("_", " ")
    return f"Step {s['k']}: {what}" + (f" {state}" if state else "") + "."


def voice_keywords(plan: dict | None) -> list[str]:
    """Muse Voice Transcribe `keywords` (terms it might mishear): the fixed command words plus the plan's valve
    names. Biases hearing only; parse_intent still needs exact words, so nothing matches loosely."""
    fixed = {w for ws in WORDS.values() for w in ws} | {"step", "done", "mark", "complete", "why", "blocked"}
    fixed |= {w for ws in STATE_WORDS.values() for w in ws}
    valves = {t for s in (plan or {}).get("steps", []) for t in _step_words(s)[0]}
    return sorted(fixed | valves)


def parse_intent(text: str, plan: dict | None) -> tuple[str, int | None, str]:
    """(intent, k, read_back). A step only from its number, or from a phrase naming ALL its targets and its
    state; anything else is `unknown` with a clarifying question, never a guess at a step."""
    toks = _tokens(text)
    words = set(toks)
    steps = [s for s in (plan or {}).get("steps", []) if s["kind"] != "final"]
    if words & NOT_BY_VOICE:
        return "unknown", None, "Signing, verifying and reopening are done on screen, not by voice."
    if "why" in words:
        return "why", None, ""
    for intent in ("cancel", "confirm", "repeat", "status"):
        if words & WORDS[intent] and len(toks) <= 3:
            return intent, None, {"cancel": "Cancelled. Nothing was marked.", "confirm": "Confirmed."}.get(intent, "")
    if "step" in toks and toks.index("step") + 1 < len(toks) and toks[toks.index("step") + 1].isdigit():
        k = int(toks[toks.index("step") + 1])
        hit = [s for s in steps if s["k"] == k]
        if hit:
            return "step_done", k, f"{_step_text(hit[0])} Say confirm to mark it done, or cancel."
        return "unknown", None, f"There is no step {k} to mark. Which step is done?"
    # a target is heard as itself, run together ("f 1" -> f1), or spoken as a word plus number ("feed one" -> f1)
    joined = set(toks) | {a + b for a, b in itertools.pairwise(toks)} | {
        a[0] + b for a, b in itertools.pairwise(toks) if b.isdigit() and not a.isdigit()}
    said = {st for st, ws in STATE_WORDS.items() if words & ws}
    named = {_norm(t) for s in steps for t in _step_words(s)[0] if _norm(t) in joined}  # every plan valve the phrase names
    hits = []
    for s in steps:
        targets, state = _step_words(s)
        if targets and state and {_norm(t) for t in targets} == named and said == {state}:  # exactly this step's valves
            hits.append(s)
    if len(hits) == 1:
        return "step_done", hits[0]["k"], f"{_step_text(hits[0])} Say confirm to mark it done, or cancel."
    return "unknown", None, "I did not catch which step. Say the step number, or every valve of the step and its state."


def _say(verdict: str | None) -> str:
    return {"BLOCKED": "blocked", "ESCALATED": "escalated", NDF: "no discrepancy found, awaiting sign-off"}.get(verdict, "evaluating")


def answer(transcript: str, d: dict | None) -> tuple[str, int | None, str]:
    """(intent, k, read_back) for a transcript against a session detail `d` (or none)."""
    intent, k, read_back = parse_intent(transcript, d["plan"] if d else None)
    if intent in ("status", "why") and d is None:
        intent, read_back = "unknown", "Which session? Open a job first."
    elif intent == "status":
        nxt = next((s for s in d["steps"] if s["marked_by"] is None and s["kind"] != "final"), None)
        read_back = (f"Data checks: {_say(d['verdict'])}. With camera: {_say(d['verdict_with_camera'])}. "
                     + (f"Next: {_step_text(nxt)}" if nxt else "Every step is marked."))
    elif intent == "why":
        reasons = ((d["tracks"]["data_only"] or {}).get("reasons") or [])
        read_back = " ".join(reasons) or f"Data checks: {_say(d['verdict'])}. No open reasons are logged."
    return intent, k, read_back
