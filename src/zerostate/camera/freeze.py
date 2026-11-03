"""Display freeze detection, in code (never the model): an unchanged display crop while the instrument's
feedback changed by more than the agreement tolerance, measured beyond the camera lag.

"Unchanged" uses an average hash of the fixed display region, not an exact pixel hash: the frame
service adds Gaussian noise to every frame, so two captures of a frozen display never match byte for byte.
"""

from PIL import Image

HASH_SIDE = 16  # 16 x 16 = 256 bits
MIN_CONTRAST = 16  # grey levels across the thumbnail; frame noise (sigma 3) averages to far less


def ahash(img: Image.Image) -> str | None:
    """Average hash of a crop: one bit per cell of a 16 x 16 grey thumbnail, set where brighter than the mean.
    None for a crop without contrast (no display content): two blank crops say nothing about a freeze."""
    px = list(img.convert("L").resize((HASH_SIDE, HASH_SIDE), Image.Resampling.BOX).getdata())
    if max(px) - min(px) < MIN_CONTRAST:
        return None
    mean = sum(px) / len(px)
    return f"{int(''.join('1' if p > mean else '0' for p in px), 2):064x}"


def differ_pct(a: str, b: str) -> float:
    return (int(a, 16) ^ int(b, 16)).bit_count() / (HASH_SIDE * HASH_SIDE) * 100


def value_at(feedback: list, t: float) -> float | None:
    """Feedback value in force at time t: the last sample at or before t (feedback sorted by time)."""
    before = [v for ft, v in feedback if ft <= t]
    return before[-1] if before else None


def frozen(captures: list[dict], feedback: list, lag_s: float, same_pct: float, change_pct: float) -> str | None:
    """captures: [{t, crop_hash, feedback_at}] of one display, earlier bursts first; feedback: [[t, value]]
    covering the latest burst. Returns a reason when a later crop matches an earlier one although the feedback
    moved by more than change_pct between the earlier capture and (later capture - lag)."""
    caps = [c for c in captures if c.get("crop_hash")]
    for j, cj in enumerate(caps):
        later = value_at(feedback, cj["t"] - lag_s)
        for ci in caps[:j]:
            if cj["t"] - lag_s <= ci["t"] or ci.get("feedback_at") is None or later is None:
                continue
            if differ_pct(ci["crop_hash"], cj["crop_hash"]) <= same_pct and abs(later - ci["feedback_at"]) > change_pct:
                return (f"display frozen: crop unchanged from {ci['t']:.1f} to {cj['t']:.1f} s while the "
                        f"instrument moved from {ci['feedback_at']:.1f} % to {later:.1f} %")
    return None
