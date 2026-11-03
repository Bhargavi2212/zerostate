"""Photo of an isolation sheet, or page 1 of a PDF (rendered with pypdfium2) -> IsolationList draft, in
two model calls so every route shares one guard against invented points:

1. Muse Spark transcribes the sheet verbatim (text only, no interpretation); the transcript is kept in
   the draft so the person can check the reading against the photo.
2. The transcript goes through the typed-text route (text_import), whose code guard nulls any tag that
   is not in the transcript, which blocks confirmation until a person resolves it.

Not covered: a misread tag in step 1 (e.g. XV-203 read as XV-208) passes the guard. The importer
accuracy set measures how often; the person's confirmation is the backstop.
"""

import io
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel

from zerostate.importers.text_import import import_text
from zerostate.llm.client import data_url, spark_json
from zerostate.models.envelope import IsolationList
from zerostate.models.plant_map import PlantMap

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
TRANSCRIBE_ID = "transcribe_sheet_v1"


class Transcript(BaseModel):
    text: str


def page_image(path: str | Path) -> tuple[bytes, str]:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        import pypdfium2

        pdf = pypdfium2.PdfDocument(str(p))
        try:
            img = pdf[0].render(scale=2).to_pil()
        finally:
            pdf.close()
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue(), "image/png"
    if p.suffix.lower() not in MIME:
        raise ValueError(f"{p.name}: expected a .png, .jpg or .pdf file")
    return p.read_bytes(), MIME[p.suffix.lower()]


def transcribe(img: bytes, mime: str, opener=None) -> str:
    prompt = (files("zerostate.llm") / "prompts" / f"{TRANSCRIBE_ID}.md").read_text(encoding="utf-8")
    msgs = [{"role": "system", "content": prompt},
            {"role": "user", "content": [{"type": "text", "text": "Transcribe this isolation sheet."},
                                         {"type": "image_url", "image_url": {"url": data_url(img, mime)}}]}]
    return spark_json(msgs, Transcript, f"transcribe_image:{TRANSCRIBE_ID}", opener=opener).text


def import_image(path: str | Path, pmap: PlantMap, opener=None) -> tuple[IsolationList, str]:
    """(list, transcript): the list is grounded in the transcript exactly like a typed text."""
    img, mime = page_image(path)
    transcript = transcribe(img, mime, opener)
    return import_text(transcript, pmap, opener, route="image"), transcript
