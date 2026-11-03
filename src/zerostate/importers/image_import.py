"""Photo of an isolation sheet, or page 1 of a PDF (rendered with pypdfium2) -> Muse Spark (strict JSON)
-> IsolationList draft. Same prompt and rules as the typed route; a person confirms the result."""

import io
from pathlib import Path

from zerostate.importers.text_import import PROMPT_ID, system_prompt
from zerostate.llm.client import data_url, spark_json
from zerostate.models.envelope import IsolationList
from zerostate.models.plant_map import PlantMap

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


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


def import_image(path: str | Path, pmap: PlantMap, opener=None) -> IsolationList:
    img, mime = page_image(path)
    msgs = [{"role": "system", "content": system_prompt(pmap)},
            {"role": "user", "content": [{"type": "text", "text": "The isolation sheet is in this image."},
                                         {"type": "image_url", "image_url": {"url": data_url(img, mime)}}]}]
    lst = spark_json(msgs, IsolationList, f"import_image:{PROMPT_ID}", opener=opener)
    return lst.model_copy(update={"plant": pmap.plant})
