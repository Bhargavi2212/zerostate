"""One display read: crop the located box with 15 % padding, enlarge x3, single Muse Spark read with a
strict-JSON reply. Anything not clearly readable comes back unreadable (value None), never a guess.
3-read voting is not built (a "should")."""

import io
from importlib.resources import files

from PIL import Image
from pydantic import BaseModel

from zerostate.llm.client import data_url, spark_json

PROMPT_ID = "read_display_v2"  # v2: right-aligned single digits (incl. 0) are complete; v1 kept for older readings
PAD, UPSCALE = 0.15, 3


class DisplayRead(BaseModel):
    value: float | None
    readable: bool


def crop(img: Image.Image, box) -> Image.Image:
    x1, y1, x2, y2 = box
    px, py = (x2 - x1) * PAD, (y2 - y1) * PAD
    c = img.crop((max(0, int(x1 - px)), max(0, int(y1 - py)), min(img.width, int(x2 + px)), min(img.height, int(y2 + py))))
    return c.resize((c.width * UPSCALE, c.height * UPSCALE), Image.Resampling.LANCZOS)


def read_display(img: Image.Image, box, spark=spark_json) -> dict:
    """{value, readable}. Raises ModelUnavailable when the model can't be asked or answers badly."""
    buf = io.BytesIO()
    crop(img, box).convert("RGB").save(buf, "PNG")
    prompt = (files("zerostate.llm") / "prompts" / f"{PROMPT_ID}.md").read_text(encoding="utf-8")
    msgs = [{"role": "system", "content": prompt},
            {"role": "user", "content": [{"type": "text", "text": "Read this display."},
                                         {"type": "image_url", "image_url": {"url": data_url(buf.getvalue(), "image/png")}}]}]
    r = spark(msgs, DisplayRead, f"camera_read:{PROMPT_ID}")
    readable = bool(r.readable and r.value is not None)
    return {"value": r.value if readable else None, "readable": readable}
