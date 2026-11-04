# ZeroState — measured behaviour of Meta models

Only measured results go here, with date and setup. This file feeds the README section on the models. Wording rules: PROJECT.md "never say" list.

## Oct 27 — first test (`D:\grfics\zerostate_test.py`, GRFICS 3D view)
- SAM 3.1 found tanks (score ~0.94) and displays (~0.8). It found **zero** "valve" objects, so a valve is located as the actuator under its display plus a layout map.
- Muse Spark read close-up digital displays correctly 6 of 7 times, after correcting for the timing between frame capture and plant data.
- Muse Spark returned "unreadable" on tiny crops → crop and upscale before reading.

## Nov 3 — first calls through the egress proxy (lab, zerostate container → zs-proxy → api.meta.ai)
- `muse-spark-1.3`: strict-JSON reply validated on the first attempt (23 in / 35 out tokens, 0.000177 USD). `sam-3.1`: 1 image, 1.45 s, 0.0025 USD. Both rows in the credit ledger.
- SAM 3.1 returns boxes **in pixels** of the sent frame (not normalised); `camera/locate.to_pixels` already accepts both.
- Headless render (zs-frames, Chromium): the Unity scene renders; at 1920x1080 the page's default camera shows all four valve displays. Prompt "digital display showing a number" gave 5 boxes: the 4 valve displays (score 0.63–0.69) and the page's "0/9" counter (no region matches it).
- Display regions = SAM's box per display + 3 px. The first hand-drawn regions (wider margins) gave IoU 0.26 with SAM's f1 box, under `MIN_IOU` 0.3: they would have read "display not located".
- **Camera check, 3 frames × 4 displays** (valves set through the operator at 25/50/75/10, 100/0/0/100 and 60/33/5/88 %, truth from the frame's sidecar, 1.9 s after capture): SAM locate → region match → Muse Spark read gave **12/12 within 1 %** (all exact). Idealised camera (renders the simulator's true state). Not the C7 measurement: that is the sealed 100-frame set.
- Spend after these checks: 0.042 USD.

## Nov 3 — Muse Voice Transcribe access (P2-5 "find, don't guess")
- Documented at https://dev.meta.ai/docs/speech-to-text and https://dev.meta.ai/docs/api-reference/voice/transcribe (model list: https://dev.meta.ai/docs/models#muse-voice-transcribe). Model `muse-voice-transcribe-1.0`, `POST https://api.meta.ai/v1/asr/transcribe`, multipart (`request` JSON part + `audio` WAV part: mono 16-bit PCM, 16 or 24 kHz), mode `PUSH_TO_TALK`. Listed price 0.18 USD per hour of audio.
- Probe with our key through zs-proxy: 1 s of silence → HTTP 200, `{"transcript": "", "audioDurationMs": 1040}`. The key has access, so the local open-weights fallback (D3) is not needed.
- Muse Spark 1.3's own audio input is documented as "not fully supported" (dev.meta.ai models page): voice goes Transcribe → intent, never audio into Spark.
- Accuracy is not measured yet: the 20-clip test (bar ≥ 18/20, 0 wrong-step mappings) needs the recorded clips.

## Nov 3 — camera zeros: read prompt v2 + calibrated-map fallback (not part of C7)
- Check frames (unsealed lab session, `D:\grfics\cam_checks`): with S8's fault (f1 stuck open, feedback faulted) the PLC reported f1 0 % while truth was 100 %; the display showed 100 and SAM + Muse Spark read 100 (frame sha256 34b1b13d…88b275). With all four valves closed, v1 + SAM-only located 2 of 4 displays and read one "0" (sha256 440718c6…8d2a8c).
- Fix (8cc2e53): `read_display_v2` (right-aligned single digits, incl. 0, are complete; never drop a digit) and, when SAM misses a mapped display, reading the display's calibrated region (fixed-camera calibration), logged `located_by: map`.
- **Zero-heavy sealed check set** (25 frames, tuning seed 2, values drawn from 0/1/5/10/100; hash list 113dbc5 committed before any read): **96/100 exact within 1 %, 0 wrong values, 0 non-zero displays read as 0.** By displayed value: 0 → 33/35, 1 → 17/17, 5 → 19/19, 10 → 14/14, 100 → 13/15. The 4 unreadable readings are all on frame_000, which is the scene's loading screen (first request after a frame-service restart): no display was visible, so unreadable is correct. Located by SAM 96, by the calibrated map 4 (frame_000).
- Reported separately from C7; C7 stays "reading accuracy, idealised camera, fault-free frames" (v1, SAM only).
