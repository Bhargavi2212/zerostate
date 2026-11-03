"""Camera reading accuracy (C7) on the frames set (eval/tools/capture_frames.py; frames outside git, their
hash list in eval/frames_set/hashes.txt). Idealised camera on P1: the 3D page renders the simulator's state.

Two halves, because model calls run only inside the zerostate container (through the egress proxy):

  (a) run, inside the container (needs MODEL_API_KEY there; about 100 x (1 SAM image + 1 Spark read per display)):
        docker cp D:/grfics/frames_set zerostate:/tmp/frames_set      (frames + .set.json; sidecars not needed)
        docker cp eval/read_accuracy.py zerostate:/tmp/read_accuracy.py
        docker exec -u zs zerostate python /tmp/read_accuracy.py run --frames /tmp/frames_set --out /data/read_out.json
        docker cp zerostate:/data/read_out.json eval/results/read_out_<date>.json
  (b) score, on the host (no model), labels from the truth sidecars:
        python eval/read_accuracy.py score eval/results/read_out_<date>.json --frames D:/grfics/frames_set --report eval/results/read_<date>.json
"""

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent


# ---- (a) run, inside the container ----------------------------------------------------------------
def run(frames: Path, display_map: Path, out: Path) -> None:
    from PIL import Image

    from zerostate.camera.locate import locate
    from zerostate.camera.read import read_display
    from zerostate.camera.track import load_display_map
    from zerostate.llm.client import ModelUnavailable

    dmap = load_display_map(display_map)
    results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}  # resumable
    for jpg in sorted(frames.glob("frame_*.jpg")):
        if jpg.stem in results:
            continue
        view = json.loads(jpg.with_suffix(".set.json").read_text(encoding="utf-8"))["view"]
        regions = {p: box for p, (v, box) in dmap.items() if v == view}
        data = jpg.read_bytes()
        img = Image.open(io.BytesIO(data))
        res = {}
        try:
            boxes = locate(data, img.size, regions)
        except ModelUnavailable as e:
            boxes, res["error"] = dict.fromkeys(regions), str(e)
        for p, box in boxes.items():
            try:
                res[p] = read_display(img, box) if box else {"value": None, "readable": False, "note": "not located"}
            except ModelUnavailable as e:
                res[p] = {"value": None, "readable": False, "note": f"read unavailable: {e}"}
        results[jpg.stem] = res
        out.write_text(json.dumps(results, indent=1), encoding="utf-8")
        print(jpg.stem, flush=True)


# ---- (b) score, on the host ---------------------------------------------------------------------
def label(sidecar: dict, point: str) -> float | None:
    """What the display should show: the simulator's measured valve position at the capture."""
    truth = sidecar.get("truth") or {}
    return (truth.get("measured") or {}).get(f"{point}_valve_pos")


def score(outputs: dict, labels: dict) -> dict:
    """outputs: {frame: {point: {value, readable}}}; labels: {frame: {point: value}}."""
    per: dict[str, dict] = {}
    for frame, reads in outputs.items():
        for point, r in reads.items():
            if not isinstance(r, dict) or labels.get(frame, {}).get(point) is None:
                continue
            want, s = labels[frame][point], per.setdefault(point, {"n": 0, "exact_1pct": 0, "within_5pct": 0, "unreadable": 0})
            s["n"] += 1
            if not r.get("readable") or r.get("value") is None:
                s["unreadable"] += 1
                continue
            s["exact_1pct"] += abs(r["value"] - want) <= 1
            s["within_5pct"] += abs(r["value"] - want) <= 5
    total = {k: sum(s[k] for s in per.values()) for k in ("n", "exact_1pct", "within_5pct", "unreadable")}
    for s in [*per.values(), total]:
        for k in ("exact_1pct", "within_5pct", "unreadable"):
            s[f"{k}_rate"] = round(s[k] / s["n"], 3) if s["n"] else None
    return {"set": f"P1 frames set, idealised camera, n = {len(outputs)} frames", "per_valve": per, "all": total}


def check_hashes(frames: Path, hash_list: Path) -> list[str]:
    bad = []
    for line in hash_list.read_text(encoding="utf-8").splitlines():
        h, name = line.split(maxsplit=1)
        p = frames / name
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
            bad.append(name)
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--frames", type=Path, required=True)
    r.add_argument("--map", type=Path, default=Path("/app/config/frame_service/display_map.yaml"))
    r.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("outputs", type=Path)
    s.add_argument("--frames", type=Path, required=True)
    s.add_argument("--hashes", type=Path, default=HERE / "frames_set" / "hashes.txt")
    s.add_argument("--report", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        run(a.frames, a.map, a.out)
        return 0
    bad = check_hashes(a.frames, a.hashes)
    if bad:
        print(f"STOP: frames or labels differ from the committed hash list: {bad[:5]}", file=sys.stderr)
        return 2
    outputs = json.loads(a.outputs.read_text(encoding="utf-8"))
    labels = {}
    for f in outputs:
        side = json.loads((a.frames / f"{f}.truth.json").read_text(encoding="utf-8"))
        labels[f] = {p: label(side, p) for p in outputs[f]}
    rep = score(outputs, labels)
    print(json.dumps(rep, indent=2))
    if a.report:
        a.report.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
