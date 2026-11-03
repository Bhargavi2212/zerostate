"""The only module that calls the Meta API. Every call goes through the egress proxy (explicit proxy
setting, never the environment), is logged with its cost to the credit ledger, and is refused once the
ledger passes the budget (a stop for a runaway loop, not a spending plan).

The API key is read from MODEL_API_KEY at call time and only ever placed in the request header; it is
never logged, printed or put into an exception.
"""

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

BASE = "https://api.meta.ai/v1"
SPARK, SAM = "muse-spark-1.3", "sam-3.1"
PRICE = {"spark_in_per_m": 1.25, "spark_out_per_m": 4.25, "sam_per_image": 2.50 / 1000}
BOX = re.compile(r"<\|box;([^|]*)\|>")


class ModelUnavailable(Exception):
    """The call could not be made or answered (network, HTTP error, budget, invalid reply)."""


def _ledger() -> Path:
    return Path(os.environ.get("ZS_CREDITS", str(Path(os.environ.get("ZS_DATA", "/data")) / "credits.jsonl")))


def _opener():
    proxy = os.environ.get("ZS_PROXY", "http://172.30.0.2:8888")
    return urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy, "http": proxy}))


def spent_usd() -> float:
    p = _ledger()
    if not p.exists():
        return 0.0
    return sum(json.loads(line)["usd"] for line in p.read_text(encoding="utf-8").splitlines() if line.strip())


def _record(model: str, purpose: str, usd: float, **counts) -> None:
    p = _ledger()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "model": model, "purpose": purpose,
                             **counts, "usd": round(usd, 6)}) + "\n")


def _post(path: str, body: dict, accept: str = "application/json", opener=None, timeout: float = 180):
    budget = float(os.environ.get("ZS_BUDGET_USD", "75"))
    if spent_usd() >= budget:
        raise ModelUnavailable(f"model budget reached ({budget:g} USD in the ledger): raise ZS_BUDGET_USD to continue")
    key = os.environ.get("MODEL_API_KEY", "")
    if not key:
        raise ModelUnavailable("MODEL_API_KEY is not set")
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "Accept": accept})
    try:
        return (opener or _opener()).open(req, timeout=timeout)
    except urllib.error.HTTPError as e:  # rebuilt without the request: its headers carry the key
        raise ModelUnavailable(f"{path}: HTTP {e.code}") from None
    except OSError as e:
        raise ModelUnavailable(f"{path}: {type(e).__name__}: {str(e).replace(key, '***')[:200]}") from None


def data_url(image: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64," + base64.b64encode(image).decode()


def spark_json(messages: list[dict], schema: type[BaseModel], purpose: str, opener=None) -> BaseModel:
    """Muse Spark with a strict-JSON reply validated against `schema`; one retry, then ModelUnavailable."""
    for attempt in (1, 2):
        with _post("/chat/completions", {"model": SPARK, "messages": messages}, opener=opener) as r:
            try:
                reply = json.loads(r.read())
                content = reply["choices"][0]["message"]["content"] or ""
            except (ValueError, KeyError, IndexError):
                raise ModelUnavailable(f"{purpose}: unreadable reply body") from None
        usage = reply.get("usage", {})
        tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        _record(SPARK, purpose, tin / 1e6 * PRICE["spark_in_per_m"] + tout / 1e6 * PRICE["spark_out_per_m"],
                input_tokens=tin, output_tokens=tout, attempt=attempt)
        text = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return schema.model_validate_json(text)
        except ValidationError:
            continue
    raise ModelUnavailable(f"{purpose}: reply was not valid JSON for {schema.__name__} after a retry")


def parse_boxes(text: str) -> list[dict]:
    """SAM 3.1 streams boxes as <|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..;c=..|> tokens."""
    out = []
    for m in BOX.finditer(text):
        f = dict(kv.split("=", 1) for kv in m.group(1).split(";") if "=" in kv)
        try:
            out.append({**{k: float(f[k]) for k in ("x1", "y1", "x2", "y2")}, "c": float(f.get("c", "nan"))})
        except (KeyError, ValueError):
            continue
    return out


def sam_boxes(image: bytes, prompt: str, purpose: str, opener=None) -> list[dict]:
    body = {"model": SAM, "stream": True, "metadata": {"include_confidence": "true"},
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": data_url(image)}]}]}
    text, t0 = "", time.monotonic()
    with _post("/responses", body, accept="text/event-stream", opener=opener, timeout=120) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "response.output_text.delta":
                text += ev.get("delta", "")
    _record(SAM, purpose, PRICE["sam_per_image"], images=1, wall_s=round(time.monotonic() - t0, 2))
    return parse_boxes(text)
