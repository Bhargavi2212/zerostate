"""Importer accuracy (C14): field-level precision / recall per route against the gold lists in
eval/importer_set/cases.yaml (authored by us, n = 12), and the count of invented points, which must be 0.

Two halves, because model calls run only inside the zerostate container (through the egress proxy):

  (a) run, inside the container (needs MODEL_API_KEY there; costs model credits):
        docker cp eval/importer_set zerostate:/tmp/importer_set
        docker cp eval/importer_accuracy.py zerostate:/tmp/importer_accuracy.py
        docker exec -u zs zerostate python /tmp/importer_accuracy.py run --set /tmp/importer_set --maps /app/config --out /data/importer_out.json
        docker cp zerostate:/data/importer_out.json eval/results/importer_out_<date>.json
  (b) score, on the host (no model):
        python eval/importer_accuracy.py score eval/results/importer_out_<date>.json --report eval/results/importer_<date>.json

The CSV route has no model and no case inputs of its own: each gold list is written as an export and
parsed back (hold time excluded, the export has no hold column). A gold list with a null tag can't be
written as an export, so it is counted as refused, which is the expected result.
"""

import argparse
import csv
import io
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

from zerostate.models.envelope import IsolationList
from zerostate.models.plant_map import PlantMap

HERE = Path(__file__).parent


def load_cases(set_dir: Path) -> list[dict]:
    return yaml.safe_load((set_dir / "cases.yaml").read_text(encoding="utf-8"))["cases"]


# ---- (a) run, inside the container ----------------------------------------------------------------
def run(set_dir: Path, maps_dir: Path, out: Path) -> None:
    from zerostate.importers.image_import import import_image
    from zerostate.importers.text_import import import_text

    results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}  # resumable
    for c in load_cases(set_dir):
        if c["id"] in results and results[c["id"]]["list"] is not None:
            continue
        plant = c["gold"]["plant"]
        pmap = PlantMap.model_validate(yaml.safe_load((maps_dir / plant / "plant_map.yaml").read_text(encoding="utf-8")))
        src = set_dir / c["input"]
        try:
            lst = (import_text(src.read_text(encoding="utf-8"), pmap) if c["route"] == "text" else import_image(src, pmap))
            results[c["id"]] = {"route": c["route"], "list": lst.model_dump(mode="json"), "error": None}
        except Exception as e:  # noqa: BLE001 - recorded per case; scoring counts it as a miss
            results[c["id"]] = {"route": c["route"], "list": None, "error": f"{type(e).__name__}: {e}"}
        out.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(c["id"], "error" if results[c["id"]]["error"] else "ok", flush=True)


# ---- (b) score, on the host ---------------------------------------------------------------------
def facts(lst: IsolationList, hold: bool = True) -> Counter:
    """One fact per field the author wrote. A point is keyed by its tag (by its seq when the tag is null)."""
    f = Counter([("work_equipment", lst.work_equipment)])
    f.update([("vent", lst.vent)] if lst.vent else [])
    f.update([("hold_minutes", float(lst.hold_minutes))] if hold and lst.hold_minutes is not None else [])
    for p in lst.points:
        key = p.tag or f"?seq{p.seq}"
        f.update([(key, "point"), (key, "required_state", p.required_state), (key, "seq", p.seq)])
        f.update([(key, "isolation_type", p.isolation_type)] if p.required_state == "closed" or p.isolation_type else [])
        f.update([(key, "lock_id", p.lock_id)] if p.lock_id else [])
    f.update(("proving", g.tag, tuple(sorted(g.proves))) for g in lst.proving)
    return f


def invented(out: IsolationList, gold: IsolationList) -> int:
    """Output points the author didn't write. A guess in place of a gold null tag is a wrong field, not
    an invented point; anything beyond the gold points is invented."""
    extra = Counter(p.tag for p in out.points) - Counter(p.tag for p in gold.points if p.tag)
    return max(0, sum(extra.values()) - sum(1 for p in gold.points if p.tag is None))


def to_csv(lst: IsolationList) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["work_order", "equipment", "tag", "required_state", "apply_seq", "isolation_type", "lock_id",
                "vent_tag", "proving_tag", "proves"])
    for i, p in enumerate(lst.points):
        g = lst.proving[i] if i < len(lst.proving) else None
        w.writerow(["WO-1", lst.work_equipment or "", p.tag or "", p.required_state or "", p.seq if p.seq is not None else "",
                    p.isolation_type or "", p.lock_id or "", lst.vent or "", g.tag if g else "", ";".join(g.proves) if g else ""])
    return buf.getvalue()


def score(outputs: dict, cases: list[dict], tmp: Path) -> dict:
    from zerostate.importers.csv_import import CsvImportError, parse_csv

    routes = {r: {"cases": 0, "tp": 0, "fp": 0, "fn": 0, "invented": 0, "errors": []} for r in ("text", "image", "csv")}
    for c in cases:
        gold = IsolationList.model_validate(c["gold"])
        got = outputs.get(c["id"], {})
        attempts = [(c["route"], got.get("list"), True, got.get("error") or ("no output" if not got else None))]
        p = tmp / f"{c['id']}.csv"
        p.write_text(to_csv(gold), encoding="utf-8")
        try:
            attempts.append(("csv", parse_csv(p, gold.plant).model_dump(mode="json"), False, None))
        except CsvImportError as e:
            attempts.append(("csv", None, False, f"refused: {e}"))
        for route, out, hold, err in attempts:
            r = routes[route]
            r["cases"] += 1
            want = facts(gold, hold)
            if out is None:
                r["fn"] += sum(want.values())
                r["errors"].append(f"{c['id']}: {err}")
                continue
            lst = IsolationList.model_validate(out)
            have = facts(lst, hold)
            tp = sum((want & have).values())
            r["tp"] += tp
            r["fp"] += sum(have.values()) - tp
            r["fn"] += sum(want.values()) - tp
            r["invented"] += invented(lst, gold)
    for r in routes.values():
        r["precision"] = round(r["tp"] / (r["tp"] + r["fp"]), 3) if r["tp"] + r["fp"] else None
        r["recall"] = round(r["tp"] / (r["tp"] + r["fn"]), 3) if r["tp"] + r["fn"] else None
    return {"set": "authored by us, n = 12", "routes": routes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--set", type=Path, default=HERE / "importer_set")
    r.add_argument("--maps", type=Path, default=Path("/app/config"))
    r.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("outputs", type=Path)
    s.add_argument("--set", type=Path, default=HERE / "importer_set")
    s.add_argument("--report", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        run(a.set, a.maps, a.out)
        return 0
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        rep = score(json.loads(a.outputs.read_text(encoding="utf-8")), load_cases(a.set), Path(tmp))
    print(json.dumps(rep, indent=2))
    if a.report:
        a.report.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    if any(r["invented"] for r in rep["routes"].values()):
        print("STOP: invented point", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
