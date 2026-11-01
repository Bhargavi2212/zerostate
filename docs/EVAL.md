# ZeroState — evaluation design

Status: approved design, revised Oct 31 after independent review. Written before the system so the test can't be shaped around the result. Wording rules: PROJECT.md "never say" list.

## Units and ground truth
- **Plan case**: one envelope (correct, or with one planted error) → plan-check verdict. Truth = planted label.
- **Live episode**: plan → steps by `plants/*/operator.py` → proof → verdict. Truth from simulator internals (`plants/*/truth.py`), which ZeroState can't reach (network test).
- **Unsafe** live episode: at the moment ZeroState returns `NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF`, any of: true work-segment pressure > 150 kPa abs (P1) / > 0.5 barg (P2); true flow through an isolated line > 1% of that line's full scale; a required step skipped; an isolation point in the wrong true state.
- Hold window fixed per plant before sealing (P1: 90 process-seconds; wall time = 90 / `process_time_scale`).

## Pre-registration (not "blind" — one person builds both sides)
1. Before tuning: write `eval/scenarios/*.yaml`, draw seeds into `eval/sealed/manifest.json` with disjoint ranges for tuning and scoring; commit only `SHA-256(salt + manifest)`; keep salt and manifest outside the repo.
2. Tune thresholds only on tuning seeds.
3. Score run uses scoring seeds; then publish manifest + salt so anyone can verify the hash and re-score from committed logs.
P2 faults and physics are fixed (committed) before any P2 threshold is tuned.

## Plants
- **P1 GRFICSv3** (Modbus) — live-evidence testbed; patched: transmitter noise ~0.1% of span on measured values with low-flow cutoff, valve-position feedback faults, leak term at zero position, time scale ×10 (decision 8; fallback ×5 or real time per decision 19), all stated as modifications. Envelope declares "positive isolation upstream assumed".
- Episode validity: the runner checks router rules and Suricata rules before and after each episode, and requires sid 9100002 > 0 (operator writes seen) and 9100001 = 0. Any failure → episode invalid, re-run, and the count of invalid episodes is reported.
- **P2 gas line** (OPC UA, ours) — plan + live testbed (spec due Nov 1 night).
- **Plan-check set** on P2's plant map (if P2 is cut: on a hand-drawn plant map of the same design, stated as synthetic).
Generality claim (C2) requires the same code with only `plants/*` changed, on ≥ 2 plants; otherwise C2 is withdrawn.

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
| S1b | gauge frozen **after** vent at true value | BP Amoco | ✓ via noise loss only — result labelled "depends on our noise model" | ✓ (post-hold bleed crack + noise loss) |
| S2 | gauge dropout to 0 (GRFICS: 10 s duty cycle) | failed-low transmitter | ✓ | ✓ |
| S3 | gauge drifting low | BP Texas City 2005 | ✓ (needs large severity; max ~0.08%/s observed) | ✓ |
| S4 | valve commanded closed, passing | Tosco 1999 | ✓ (patch) | ✓ |
| S5 | wrong valve operated | Formosa 2004 | ✓ | ✓ |
| S6 | PLC in AUTO reopens a valve closed from the screen | HSG253 case | ✓ | — |
| S7 | step skipped / same person installs and verifies | BP Amoco | ✓ | ✓ |
| S8 | valve position feedback lies | Giant 2004, Milford Haven 1994 | ✓ (patch) | ✓ (physics only, no camera) |
| S10 | blocked vent (no flow when opened) | Tosco drains | — | ✓ |
| S11 | dry test (no upstream pressure during hold) | WMC MHS-07 | — | ✓ |
| S12 | comms loss / stale registers (incl. whole-path freeze: every tag behind the PLC, also closed-valve groups, must leave GOOD) | Modbus last-value behaviour; seen live Oct 31 (~50 s frozen with successful reads) | ✓ | ✓ |
| S9 | replayed values | Stuxnet | stretch | stretch |
Target: 5 episodes per scenario per plant, 15 clean per plant (Decision 8). Run overnight Nov 2.

## Systems compared
1. Gauge rule (hurried human): pass when pressure < threshold and flows ≈ 0.
2. Muse Spark alone, same data.
3. ZeroState data-only — **headline**.
4. ZeroState + idealised camera (P1) — reported separately, labelled.
Ablations: LIVE-ALIVE off; LIVE-RELATION off.

## Metrics
- Dangerous misses: count/n, Wilson 95% CI; 0/n reported as upper bound ≈ 3/n.
- False blocks on clean episodes / correct plans.
- Time to block; severity at release (true pressure/flow when released; Urbina 2016).
- Camera reading: exact match and `unreadable` rate on a sealed frame set: 100 frames per plant state class, labelled from truth at the frame's capture time (frame service stamps truth beside each frame; ZeroState never sees it).
- Importer (if built): field-level precision/recall on 10 isolation sheets drawn from real public procedure formats (Seqwater, NPDC, Marathon templates) filled by someone other than the importer's prompt author where possible; stated as small-n.
- Not used: point-adjusted F1, text similarity, LLM-as-judge scoring.

## Checks on our own work
- P2 physics compared with the analytic blowdown solution — this checks the **implementation**, not realism (same equations), and is labelled so. If time: compare against an OpenModelica Modelica.Fluid run (independent implementation).
- Practitioner review: only if Decision 10 confirms a person; otherwise not mentioned.
- All logs, manifest and salt published for re-scoring.

## Known blind spots and dependencies (reported, not hidden)
- Freeze / stale detection (S1, S1b, S12, C9) relies on transmitter noise **we add** to both simulators. A real frozen transmitter that keeps emitting noise, or a plant with quantised/noise-free signals, would not be caught this way. Every such result is labelled "depends on our noise model".
- P1 S1b without the noise model: undetectable from data (no post-hold disturbance).
- P1: no upstream sensor, so no dry-test check.
- Camera on P1 renders truth (idealised).
- Replay (S9) stays stretch: our noise is pseudo-random, so replay detection would be testing our own generator.

## What we learned about Meta's models (measured only)
Oct 27: SAM 3.1 found tanks (~0.94) and displays (~0.8), zero "valve" objects; Muse Spark read close-up digital displays (6/7 after timing correction), "unreadable" on tiny crops.
