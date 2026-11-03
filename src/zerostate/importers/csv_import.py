"""SAP WCM / Maximo-style isolation export (CSV) -> IsolationList. Exact parse, no model: any error is
raised with its row number, never guessed around.

One row per isolation point. `equipment`, `work_order` and `vent_tag` repeat on every row and must
agree. `proving_tag` + `proves` (tags separated by `;`) on a row add one proving entry.
"""

import csv
from pathlib import Path

from zerostate.models.envelope import IsolationList, ListPoint, ListProving

COLUMNS = ("work_order", "equipment", "tag", "required_state", "apply_seq", "isolation_type", "lock_id",
           "vent_tag", "proving_tag", "proves")
STATES = {"open", "closed"}
TYPES = {"positive", "proved", "non_proved"}


class CsvImportError(ValueError):
    pass


def parse_csv(path: str | Path, plant: str) -> IsolationList:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    missing = [c for c in COLUMNS if c not in (reader.fieldnames or ())]
    if missing:
        raise CsvImportError(f"row 1: missing columns {missing}")
    if not rows:
        raise CsvImportError("no rows after the header")
    points, proving, same = [], {}, {}
    for n, r in enumerate(rows, start=2):  # row 1 is the header
        v = {c: (r[c] or "").strip() for c in COLUMNS}
        for c in ("work_order", "equipment", "vent_tag"):
            if same.setdefault(c, v[c]) != v[c]:
                raise CsvImportError(f"row {n}: {c} {v[c]!r} differs from {same[c]!r} on earlier rows")
        if not v["tag"]:
            raise CsvImportError(f"row {n}: empty tag")
        if v["required_state"].lower() not in STATES:
            raise CsvImportError(f"row {n}: required_state {v['required_state']!r} is not open/closed")
        try:
            seq = int(v["apply_seq"])
        except ValueError:
            raise CsvImportError(f"row {n}: apply_seq {v['apply_seq']!r} is not an integer") from None
        itype = v["isolation_type"].lower().replace("-", "_") or None
        if itype and itype not in TYPES:
            raise CsvImportError(f"row {n}: isolation_type {v['isolation_type']!r} is not one of {sorted(TYPES)}")
        points.append(ListPoint(tag=v["tag"], required_state=v["required_state"].lower(), seq=seq,
                                isolation_type=itype, lock_id=v["lock_id"] or None))
        if v["proving_tag"]:
            proves = tuple(t.strip() for t in v["proves"].split(";") if t.strip())
            if not proves:
                raise CsvImportError(f"row {n}: proving_tag {v['proving_tag']} proves nothing")
            if proving.setdefault(v["proving_tag"], proves) != proves:
                raise CsvImportError(f"row {n}: proving_tag {v['proving_tag']} proves {proves}, earlier {proving[v['proving_tag']]}")
        elif v["proves"]:
            raise CsvImportError(f"row {n}: proves given without a proving_tag")
    return IsolationList(plant=plant, work_equipment=same["equipment"] or None, points=tuple(points),
                         vent=same["vent_tag"] or None,
                         proving=tuple(ListProving(tag=t, proves=p) for t, p in proving.items()),
                         notes=(f"work order {same['work_order']}",) if same["work_order"] else ())
