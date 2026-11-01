"""P1-9: build the smoke table from runs/<episode>/ outputs (verdict.json, audit_export.json,
truth.jsonl, events.jsonl). Writes eval/results/smoke_p1_<date>.md.

    python eval/tools/smoke_table.py runs/S0_seed7_* runs/S1_seed3_* ...
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[2]


def ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []


def row(run: Path, basis: str = "") -> dict:
    v = json.loads((run / "verdict.json").read_text(encoding="utf-8"))
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    scale = meta["process_time_scale"]
    events = json.loads((run / "audit_export.json").read_text(encoding="utf-8")) if (run / "audit_export.json").exists() else []
    truth = jsonl(run / "truth.jsonl")
    marks = {e["payload"]["k"]: ts(e["ts"]) for e in events if e["kind"] == "step_done"}
    first = next((e for e in events if e["kind"] == "evaluation"
                  and e["payload"]["verdict_after"] in ("BLOCKED", "ESCALATED")), None)
    first_fail = " + ".join(f"{f['rule_id']} {f['status']}" for f in first["payload"]["findings"]
                            if f["status"] != "PASS") if first else ""
    terminal = next((ts(e["ts"]) for e in events if e["kind"] == "verdict" and e["payload"]["verdict"] in ("BLOCKED", "ESCALATED")), None)
    fault_t = next((e["data"].get("t_vm") for e in jsonl(run / "events.jsonl") if e["kind"] == "fault"), None)
    since = fault_t or marks.get(1)
    to_block = round((terminal - since) * scale) if terminal and since else ""
    vent = ""
    if 5 in marks:
        hit = next((r["t"] for r in truth if r["t"] >= marks[5] and r["outputs"]["pressure"] <= 105), None)
        vent = round((hit - marks[5]) * scale) if hit else "not reached"
    hold = ""
    if 7 in marks:
        p = [r["outputs"]["pressure"] for r in truth if r["t"] >= marks[7]]
        hold = round(min(p), 1) if p else ""
    return {"scenario": v.get("scenario"), "seed": v.get("seed"), "rules_basis": basis, "expected": "/".join(v.get("expected", [])),
            "actual": v.get("verdict") or "invalid", "match": v.get("match", False), "valid": v.get("valid", False),
            "first_block": first_fail, "to_block_process_s": to_block, "vent_to_105_process_s": vent,
            "min_hold_kpa": hold, "problems": "; ".join(v.get("problems", []))}


def main(runs: list[str]) -> int:
    # each arg: runs/<episode>[=basis], e.g. runs/S1_seed11_...=replayed under v2
    rows = [row(Path(r.split("=")[0]), r.split("=")[1] if "=" in r else "") for r in runs]
    cols = list(rows[0])
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    out = ROOT / "eval" / "results" / f"smoke_p1_{datetime.now(UTC):%Y-%m-%d}.md"
    out.write_text("# P1 smoke run (tuning seeds)\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if all(r["match"] and r["valid"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
