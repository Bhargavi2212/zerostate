"""The one never-say checker (docs/PROJECT.md "Never say" list). Eval, site and tests import it from here.

`hits(text)` returns every banned phrase found; `python -m zerostate.wording <files...>` exits 1 on any.
"""

import re
import sys
from pathlib import Path

# Each item exactly as written in PROJECT.md (tests/test_wording.py keeps the two in step), with the
# patterns that catch it. A leading "not " is allowed where the honest sentence is the negation.
NEVER_SAY: dict[str, tuple[str, ...]] = {
    "verifies isolation": (r"\bverifies isolation\b",),
    "proves / certifies zero energy": (r"\b(proves?|certif\w*)\s+zero energy\b",),
    "makes LOTO safe": (r"\bmakes LOTO safe\b",),
    "safety-rated": (r"(?<!\bnot )\bsafety[- ]rated\b",),
    "any SIL/PL/IPL credit": (r"\b(SIL|PL|IPL)\b[^.;\n]{0,20}\bcredit\b",),
    'IEC 61508/61511, OSHA or "EU AI Act" compliant': (
        r"\b(IEC 61508|61511|OSHA|EU AI Act)\b[^.;\n]{0,20}\bcomplian(t|ce)\b",
        r"\bcomplian(t|ce) with (IEC|OSHA|the EU AI Act)\b"),
    "equivalent to an AVT": (r"(?<!\bnot )\bequivalent to an? (AVT|absence-of-voltage tester)\b",),
    "reduces checks or headcount": (r"\breduces? (checks|headcount)\b",),
    "would have prevented a named incident": (r"\bwould have prevented\b",),
    "0% misses / never misses": (r"\b0 ?% misses\b", r"\bnever miss(es)?\b"),
    '"works for any plant" without naming tested plants': (r"\bworks for any plant\b",),
    '"never sees ground truth" while the camera renders the sim': (r"\bnever sees ground truth\b",),
}
DEFINITION = "Never say: "  # the PROJECT.md line that holds the list (skipped by the file check)
EXTRA = (r"\bsafe\b", r"\bfault-but-safe\b", r"\bsimulated camera\b", r"\bnot visible to ZeroState\b")

_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (*EXTRA, *(p for ps in NEVER_SAY.values() for p in ps))]


def hits(text: str) -> list[str]:
    """Every banned phrase in `text`, as found (empty list = clean)."""
    return [m.group(0) for p in _PATTERNS for m in p.finditer(text)]


def main(argv: list[str]) -> int:
    bad = 0
    for name in argv:
        for n, line in enumerate(Path(name).read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.startswith(DEFINITION):  # PROJECT.md's own list
                continue
            for h in hits(line):
                print(f"{name}:{n}: {h!r}")
                bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
