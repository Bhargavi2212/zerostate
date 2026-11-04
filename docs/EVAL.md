# ZeroState — evaluation design

Status: approved design, revised Oct 31 after independent review. Written before the system so the test can't be shaped around the result. Wording rules: PROJECT.md "never say" list.

## Units and ground truth
- **Plan case**: one envelope (correct, or with one planted error) → plan-check verdict. Truth = planted label.
- **Live episode**: plan → steps by `plants/*/operator.py` → proof → verdict. Truth from simulator internals (`plants/*/truth.py`), which ZeroState can't reach (network test).
- **Unsafe** live episode: at the moment ZeroState returns `NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF`, any of: true work-segment pressure > 150 kPa abs (P1 and P2); true flow through an isolated line > 1% of that line's full scale (P2: > 1 % of the line's flow fully open at its design pressure difference); a required step skipped; an isolation point in the wrong true state.
  **Fixed Nov 3, before the seal was opened** (DECISIONS, Nov 3; can only add misses, never remove them):
  - **Primary hazard definition** = the four conditions above, as pre-registered. References pinned per plant: P1 full scale = `scale_max` in `plants/p1_grfics/modbus_map.yaml` at `bench-freeze-p1` (f1 1000, f2 500, purge 2000, product 500); P2 = the line's flow fully open at its design pressure difference. A required step skipped = a plan step with no mark in the audit; wrong true state = truth `state.<valve>_valve_pos` more than 1 % from the step's required state.
  - **Secondary hazard definition** (stricter), added Nov 3, before the seal was opened: the same four conditions with the flow limit at 0.1 % of the same reference.
  - **Dangerous miss** = `NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF` and a condition met at any time from that verdict to the episode end. Counted under each definition, each with its own figure.
  - **Episode label** (unsafe / fault below hazard limits / clean) comes from truth after the isolation marks, whatever the verdict: a line's flow and state count from its own isolate mark, the vent valve's from the vent_close mark, pressure from the vent_close mark (not evaluated if never reached). For BLOCKED or ESCALATED episodes the label is descriptive only.
- Hold window fixed per plant before sealing (P1: `hold_process_s: 600`, real 10-minute practice; wall time = 600 / `process_time_scale`).
- Episodes are **pre-registered by seed and replayable from logs**: a seed fixes fault type, severity and onset; the plant's noise is not seeded (it runs on wall-clock ticks), so episodes are never claimed to be regenerable. Reproducibility = replay of every logged evaluation window (C11).

## Pre-registration (not "blind" — one person builds both sides)
1. Before scoring: write `eval/scenarios/*.yaml`; `eval/seal.py --batch <b>` draws scoring seeds (≥ 10000, `os.urandom`, shuffled order) into a manifest kept with a random salt **outside the repo** (`D:\grfics\sealed\`); only `eval/sealed_hash_<b>.txt = SHA-256(salt + manifest)` is committed, then the batch is tagged `bench-freeze-<b>`. Tuning seeds are 0–999. The runner refuses a scoring seed unless it is in the manifest matching the committed hash, HEAD is the batch tag, tracked files are unchanged, the plan is the committed one and the ZeroState container holds the tag's code.
   **Batches** (separately sealed; every result names its batch): **p1 — "live checks only"** (the Phase 1 engine, data-only): S0 ×15 + S1, S1b, S2, S3, S4-small, S4-large, S5, S6, S8, S12 ×5 (65; no S7) → C5, C6. **2 — "full engine (live + process + camera)"**: plan set (PC0 ×15, PC1–PC6 ×5) → C3; P1 with the camera on: S0 ×15 (the full engine's own false-block rate, C6), S7 ×5, S7-same ×5, S13 ×5 (C13), S8 ×5 (camera half of C8). **p2 — "gas line, full engine"** (own seal, only if P2's live smoke passes by Nov 3 18:00): P2 S0 ×15 + 12 fault scenarios ×5 → P2 rows of C5/C6, C2. Every result names its batch and engine label.
   An INVALID episode (pre/postflight, guard, fault not applied, vent start < 1500 kPa) is retried once with the same seed, then recorded INVALID and not counted; the INVALID rate is reported.
2. Tune thresholds only on tuning seeds.
3. Score run uses scoring seeds; then publish manifest + salt so anyone can verify the hash and re-score from committed logs.
P2 faults and physics are fixed (committed) before any P2 threshold is tuned.

## Plants
- **P1 GRFICSv3** (Modbus) — live-evidence testbed; patched: transmitter noise ~0.1% of span on measured values with low-flow cutoff, valve-position feedback faults, leak term at zero position, time scale ×10 (decision 8; fallback ×5 or real time per decision 19), all stated as modifications. Envelope declares "positive isolation upstream assumed".
- Episode validity: the runner checks router rules and Suricata rules before and after each episode, and requires sid 9100002 > 0 (operator writes seen) and 9100001 = 0. Any failure → episode invalid, re-run, and the count of invalid episodes is reported.
- **P2 gas line** (OPC UA, ours) — plan + live testbed (spec due Nov 1 night).
- **Plan-check set** on P2's plant map (if P2 is cut: on a hand-drawn plant map of the same design, stated as synthetic).
Generality claim (C2, decision D4 in PHASE_3.md; reworded Nov 4): one engine ran both plants and no plant-specific name appears in `src/` (`tests/test_plant_agnostic.py`); the `src/` changes between batch 2 and batch p2 are exactly the two rule fixes found on P2 tuning (LIVE-VALVE v2, LIVE-ALIVE v3), checked from git by the claims audit, and the published P1 episodes replay unchanged under them. If batch p2 doesn't run, C2 is withdrawn.

## Plan-check set
| ID | Planted error | Real case |
|---|---|---|
| PC0 | none (correct plans) | — |
| PC1 | energy path left open | HSG253 missed line |
| PC2 | isolation device on live side | LyondellBasell 2021 |
| PC3 | boxed-in volume with heater, no relief | Williams 2013 |
| PC4 | control-valve / software-only isolation | HSG253 case |
| PC5 | wrong tag / wrong equipment | Pemex 2024, Formosa 2004 |
| PC6 | proved isolation without proving point / bleed into pressurised header | IChemE LPB 250 |
Target: 5 variants per error, 15 correct. P1's real GRFICS plan is run separately: expected verdict BLOCKED (PLAN-SOFTWARE / PLAN-TYPE).

## Live scenarios
| ID | Scenario | Real case | P1 | P2 |
|---|---|---|---|---|
| S0 | clean isolation, healthy instruments | — | ✓ | ✓ |
| S1 | gauge frozen **during** vent | BP Amoco 2001, Buncefield | ✓ | ✓ |
| S1b | gauge frozen **after** vent at true value | BP Amoco | ✓ via noise loss only — result labelled "depends on our noise model" | ✓ PT-211/212 frozen during the 200 kPa hold + XV-204 leak 0.3–1.5 %: the final vent is the post-hold check (does not depend on our noise model) |
| S2 | gauge dropout to 0 (GRFICS: 10 s duty cycle) | failed-low transmitter | ✓ | ✓ |
| S3 | gauge drifting low | BP Texas City 2005 | ✓ (needs large severity; max ~0.08%/s observed) | ✓ |
| S4 | valve commanded closed, passing | Tosco 1999 | ✓ (patch) | ✓ |
| S5 | wrong valve operated | Formosa 2004 | ✓ | ✓ |
| S6 | PLC in AUTO reopens a valve closed from the screen | HSG253 case | ✓ | — |
| S7 | step skipped / same person installs and verifies | BP Amoco | ✓ | ✓ |
| S8 | valve position feedback lies | Giant 2004, Milford Haven 1994 | ✓ (patch) | ✓ (physics only, no camera) |
| S10 | blocked vent (no flow when opened) | Tosco drains | — | ✓ (LIVE-ALIVE: open, no flow, no fall → FAIL) |
| S11 | dry test (no upstream pressure during hold) | WMC MHS-07 | — | ✓ |
| S12 | comms loss / stale registers (incl. whole-path freeze: every tag behind the PLC, also closed-valve groups, must leave GOOD) | Modbus last-value behaviour; seen live Oct 31 (~50 s frozen with successful reads) | ✓ | ✓ |
| S13 | inch and test: f1 reopened after the block-in, closed again, not verified again (PROC-RESET) | temporary de-isolation (ETUG) | ✓ | — |
| S9 | replayed values | Stuxnet | stretch | stretch |
Target: 5 episodes per scenario per plant, 15 clean per plant (Decision 8). Run overnight Nov 2.

## Systems compared
1. Gauge rule (hurried human): pass when pressure < threshold and flows ≈ 0.
2. Muse Spark alone, same data.
3. ZeroState data-only — **headline** (the data-only verdict track, logged live and confirmed by replay).
4. ZeroState + idealised camera (renders the simulator's true state; P1) — the with-camera track of the same episodes (batch 2 subset), reported separately, labelled.
Ablations: LIVE-ALIVE off; LIVE-RELATION off.

## Metrics
- Dangerous misses (NO_DISCREPANCY, then a hazard condition met at any time until the episode end; primary and secondary definitions each reported): count/n, Wilson 95% CI; 0/n reported as upper bound ≈ 3/n.
- Missed faults (fault present, no hazard limit crossed, NO_DISCREPANCY): reported separately, never folded into dangerous misses.
- INVALID rate per batch.
- LIVE-HOLD detection rate by leak size (S4-small, S1b).
- False blocks on clean episodes / correct plans.
- Time to block; severity at release (true pressure/flow when released; Urbina 2016).
- Camera reading: exact match and `unreadable` rate on a sealed frame set: 100 frames per plant state class, labelled from truth at the frame's capture time (frame service stamps truth beside each frame; ZeroState never sees it).
- Importer: field-level precision/recall per route (CSV, text, image) on 12 cases authored by us (6 typed texts, 6 sheets rendered from our own templates in the field layouts of public procedures — Seqwater, NPDC, Marathon — with no real names or logos; 2 deliberately ambiguous, which must come back null), gold lists committed before any importer run; invented points must be 0. Stated as "authored by us, n = 12". All three routes share one guard against invented points: the photo route first transcribes the sheet verbatim, then the transcript goes through the typed route, whose code nulls any tag the author's text doesn't contain (which blocks confirmation). Stated limit: a tag misread in the transcription (e.g. XV-203 read as XV-208) passes that guard; the accuracy set measures how often, and the person's confirmation (photo, transcript and table side by side) is the backstop.
- Not used: point-adjusted F1, text similarity, LLM-as-judge scoring.

## Checks on our own work
- P2 physics compared with the analytic blowdown solution — this checks the **implementation**, not realism (same equations), and is labelled so. If time: compare against an OpenModelica Modelica.Fluid run (independent implementation).
- Practitioner review: only if Decision 10 confirms a person; otherwise not mentioned.
- All logs, manifest and salt published for re-scoring.

## Known blind spots and dependencies (reported, not hidden)
- Freeze / stale detection (S1, S1b, S12, C9) relies on transmitter noise **we add** to both simulators. A real frozen transmitter that keeps emitting noise, or a plant with quantised/noise-free signals, would not be caught this way. Every such result is labelled "depends on our noise model".
- P1 S1b without the noise model: undetectable from data (no post-hold disturbance). P2 S1b is caught by the final vent from the 200 kPa hold, independent of the noise model; results state the difference.
- P1: no upstream sensor, so no dry-test check.
- Level dropout to 0 is in range and not caught (spike/rate tests run only on pressure and level, and a 0 % level is physically possible); level is not evidence for a vapour-side isolation.
- P1 f1 leaks below ≈ 1.6 % are hidden by the 1 % low-flow cutoff and caught only by the hold test (real transmitter property, reported, not tuned away).
- Camera on P1 renders truth (idealised).
- Replay (S9) stays stretch: our noise is pseudo-random, so replay detection would be testing our own generator.

## What we learned about Meta's models (measured only)
Oct 27: SAM 3.1 found tanks (~0.94) and displays (~0.8), zero "valve" objects; Muse Spark read close-up digital displays (6/7 after timing correction), "unreadable" on tiny crops.

## Known limits (carried into the README's Limits section)
- **Camera lag was never measured.** `camera_lag_max_wall_s: 5` is the start value (the 3D page polls every 3 s), not a measured figure; LIVE-CAMERA's agreement window rests on it.
- **Importer, text route, case t02:** the model listed a real vent valve (purge) as an isolation point (1 invented point; the 0-invented bar fails). The draft could not be confirmed: the confirm screen flagged the row and the plan would not merge until it was corrected, but no message named the cause.
- **Batch p2 baselines:** the gauge rule and Muse Spark alone were run on P1 only; P2's flow reference was pinned after batch p2 ran, from the model (DECISIONS Nov 4, with a sensitivity table).
