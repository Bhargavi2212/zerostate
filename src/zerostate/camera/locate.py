"""SAM 3.1 boxes for "digital display", matched by overlap to the display regions of display_map.yaml
(view -> display region -> valve). A region with no box overlapping it enough is "not located"."""

from zerostate.llm.client import sam_boxes

PROMPT = "digital display"
MIN_IOU = 0.3


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def to_pixels(box: dict, size: tuple[int, int]) -> tuple[float, float, float, float]:
    """SAM boxes may come normalised (0..1) or in pixels: normalised ones are scaled to the frame."""
    xy = (box["x1"], box["y1"], box["x2"], box["y2"])
    if max(xy) <= 1.5:
        w, h = size
        return xy[0] * w, xy[1] * h, xy[2] * w, xy[3] * h
    return xy


def match(boxes: list[dict], regions: dict[str, list], size: tuple[int, int]) -> dict[str, tuple | None]:
    """Each region gets the box overlapping it most (IoU >= MIN_IOU), else None."""
    px = [to_pixels(b, size) for b in boxes]
    out = {}
    for name, region in regions.items():
        best = max(px, key=lambda b: iou(b, region), default=None)
        out[name] = best if best is not None and iou(best, region) >= MIN_IOU else None
    return out


def locate(frame: bytes, size: tuple[int, int], regions: dict[str, list], sam=sam_boxes) -> dict[str, tuple | None]:
    return match(sam(frame, PROMPT, purpose="camera_locate"), regions, size)
