# Voice test runs (P3-5)

Route: Muse Voice Transcribe (`muse-voice-transcribe-1.0`) → `zerostate.api.server.parse_intent` (rules, no model) on the
P1 plan. Expected intents: `eval/voice_expected.yaml` (committed before any clip). Bar: ≥ 18/20 correct and 0 wrong-step.

| Run | Clips | Config | Result file | Correct | Wrong-step | Bar |
|---|---|---|---|---|---|---|
| 1 | `voice recordings` (m4a) | no keywords | `voice_2026-11-03_run1.json` | 16/20 | 0 | not met |
| 2 | `voice recordings 2` (ogg) | keywords, `ad0a21b` | `voice_2026-11-03_run2.json` | 18/20 | 2 | not met |
| 3 (final) | `voice recordings 3` (ogg) | keywords, `ad0a21b` | `voice_2026-11-03_run3.json` | 15/20 | 0 | not met |

## Run 1
Four misses, all transcription of short words: "purge" → "Verge", "confirm" → "conform" (twice), "status" →
"straightus". Led to the Transcribe `keywords` setting (command words + plan valve names), fixed in `ad0a21b` before the
run 2 clips were recorded.

## Run 2
Score stays as run: 18/20, 2 wrong-step. The two wrong-step clips are `step2` (script "step two done", transcribed "step
three is done.") and `step 3` (script "step three is done", transcribed "step two done"). Bhargavi listened to both
files on Nov 3: the recordings were saved under each other's names. The transcriber and parser handled the audio
correctly; the swap happened at recording time, so the run is not re-scored and its bar stays not met.

## Run 3 is final
Stated before any run 3 clip exists: run 3 uses the same expected file and the same config (`ad0a21b`). Whatever it
scores is the voice result we report, next to runs 1 and 2. No change to code, keywords, expected intents or clips after
it runs.

## Run 3 (final, reported as is)
15/20 correct, 0 wrong-step: the bar is not met. Five misses, all `unknown` (none mapped to a wrong step): three transcripts
repeat a word run together ("stepstep one, done.", "confirmconfirm", "statusstatus"), two mishear the valve word ("feed one and
prudge closed.", "raj open"). Across all three runs no clip ever mapped to a step that was not said.
