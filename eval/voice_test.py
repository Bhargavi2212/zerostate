"""Voice test (P3-5): the recorded clips through the product's route, Muse Voice Transcribe -> the API's
parse_intent on the P1 plan, against eval/voice_expected.yaml (committed before any clip was transcribed).
Bar: >= 18/20 correct and 0 wrong-step mappings ("unknown" is acceptable; a wrong step is not).

    python eval/voice_test.py --clips D:/grfics/voice_wav    # WAV, mono 16-bit, 16 or 24 kHz (clips stay outside git)
"""

import argparse
import json
from datetime import date
from pathlib import Path

import yaml

from zerostate.api.server import parse_intent
from zerostate.llm import client

ROOT = Path(__file__).parents[1]


def judge(clip: dict, intent: str, k: int | None) -> dict:
    want_k = clip.get("k")
    return {"correct": intent == clip["intent"] and k == want_k,
            "wrong_step": intent == "step_done" and k != want_k}  # a step marked that was not said


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / f"voice_{date.today().isoformat()}.json")
    a = ap.parse_args()
    spec = yaml.safe_load((ROOT / "eval" / "voice_expected.yaml").read_text(encoding="utf-8"))
    plan = yaml.safe_load((ROOT / spec["plan"]).read_text(encoding="utf-8"))
    rows = []
    for clip in spec["clips"]:
        wav = (a.clips / clip["file"]).with_suffix(".wav")
        text = client.transcribe(wav.read_bytes(), "voice_test")
        intent, k, read_back = parse_intent(text, plan)
        rows.append({**clip, "transcript": text, "got": {"intent": intent, "k": k}, "read_back": read_back,
                     **judge(clip, intent, k)})
        print(f"{clip['file']:<18} {text!r:<40} -> {intent} {k if k is not None else ''}  {'OK' if rows[-1]['correct'] else 'MISS'}")
    correct, wrong = sum(r["correct"] for r in rows), sum(r["wrong_step"] for r in rows)
    out = {"asr": client.ASR, "route": "transcribe -> zerostate.api.server.parse_intent (rules, no model)",
           "n": len(rows), "correct": correct, "wrong_step": wrong,
           "bar_met": correct >= 18 and wrong == 0, "clips": rows}
    a.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"{correct}/{len(rows)} correct, {wrong} wrong-step; bar {'met' if out['bar_met'] else 'NOT met'} -> {a.out}")
    return 0 if out["bar_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
