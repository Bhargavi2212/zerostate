# Phase 3: Product surface, proof, submission (spec rev 3 + demo storyboard)

**Goal:** ship what judges see and can test.
- A real operator console.
- A lab-free replay mode anyone can run.
- A public results and replay site on Vercel.
- Sealed, scored benchmark results.
- An audited claims ledger, a README and a demo video.

**Submit by Nov 4, 18:00 ET** (the hard deadline is 21:00 ET).

Branch `p3-work`, using parallel worktrees. UI work needs no lab, so it **starts Nov 3 at 08:00**. Tag `submission`.

Rev 3 applies an independent review of rev 2 against the repo at `p2-work` 5137658, which has 310 offline tests passing. Every blocker in that review was confirmed in the code.

## 0. Decisions this spec needs from Bhargavi (Nov 3, by 08:30)

| # | Decision | Recommendation |
|---|---|---|
| D1 | **P2 live gas line.** It isn't runnable in any batch today: the runner accepts only `--plant p1`, `seal.py` has no P2 batch, there's no P2 container in compose, no 4840 rules, and no operator `p2` command. | Keep it (no rescoping), but **as its own sealed batch `p2`**, never folded into batch 2. Hard rule: **if P2's live smoke isn't passing by Nov 3 18:00, batch p2 doesn't run.** C2 is then withdrawn, and C12 stays as an offline implementation check. |
| D2 | **Camera go/no-go.** The views and display regions are still placeholders, and the headless render and lag have never been measured. | First lab job Nov 3. **If the camera isn't reading displays by 12:00**, take it out of batch 2 and the video, withdraw C7 and C8's camera half, and log it in DECISIONS. |
| D3 | **Voice speech-to-text if Muse transcription isn't available.** Chrome's built-in recognition is Google's cloud service, which breaks "no non-Meta models". | Fall back to a **Meta open-weights speech model run locally** in `zs-api` (wav2vec2 / MMS family, licence checked before use). It stays Meta-only, works offline (a real plus for plant networks), and fits the event's "run Meta open weights models". **If neither works by 13:00 Nov 3, cut voice.** Never Google speech. |
| D4 | **C2 wording.** "Changed only plant files" is false: commit 608484a generalised rules in `src/`. | Reword: "the same engine, from one commit, ran both plants; no plant-specific name appears in `src/`." Add an AST test. Withdraw it if P2 doesn't run. |

## Facts that shape this phase
- **Judging:**
  - Indie track on the public page: "creativity, technical ambition, and whether it works".
  - Participant guide (as recorded in PROJECT.md): Impact 30, Meta tooling 25, Technical depth 20, Demo 25.
  - **Check the participant guide and official rules on Nov 3 morning** for:
    - video length;
    - form fields;
    - repo rules;
    - AI coding tools used to build (we use Claude Code);
    - non-Meta models in the product (we must use none);
    - the event start date versus our Oct 27 kill test (disclose it either way).
- **Meta models in the product:**
  - Muse Spark: importer, camera reading, explain, voice intent.
  - SAM 3.1: camera display location.
  - Possibly a Meta open-weights speech model (D3).
  - **No non-Meta model anywhere in the product.**
- **Camera label everywhere:** "**idealised camera** (renders the simulator's true state)". Never "simulated camera", never "not visible to ZeroState".
- **Truth label in the viewer:** "**simulator internals — not read by ZeroState's data checks**".
- **Batches are never pooled.** Each number names its batch and engine:
  - **p1:** live checks only (Phase 1 engine), running now.
  - **2:** full engine (live + process + camera): plan set + P1 S0×15, S7, S7-same, S13, S8 ×5, camera on.
  - **p2:** gas line, full engine, its own seal, only if D1 passes.
  - **tests:** offline test suites, for claims like C1, C4, C9–C11.
- **The claims audit is Nov 4 10:00 ET.** CLAIMS.md and PROJECT.md still say Nov 3 12:00; fix them first thing (P3-0).
- **Hard rules:**
  - No screen, reply, page or file says "safe". The check is the word `\bsafe\b`, plus the full never-say list.
  - Nothing closes a session except a signature entered in the sign dialog or with `zs sign`.
  - **Agents and scripts never confirm a plan or submit a signature on real data.**
  - Names are **not authenticated** in this build. Say so.

## Cut order
1. P2 live (D1 rule).
2. Voice (D3 rule).
3. The viewer's episode scrubber (keep the results page plus the episode list).
4. Polish.

**Never cut:** claims tooling, scoring, the results page, lab-free replay mode, the console's intake and session screens, README, video.

## Items

### P3-0 Claims tooling and ledger fixes (first, Nov 3 08:00)
**Docs first, in one commit:**
- Audit deadline → Nov 4 10:00 in CLAIMS.md and PROJECT.md.
- Reword these claims:
  - **C2** per D4.
  - **C9:** "In tests and N S12 episodes, stale or frozen data never produced a pass."
  - **C10:** "No model output can produce a pass or remove a block; only a signature entered in the sign dialog or `zs sign` closes a session; names are not authenticated."
  - **C13:** "caught in K/5 each; independence means a different *entered* name."
  - **C3:** "on plan cases generated by mutation, modelled on incident patterns, authored by us."
  - **C6 and C8:** one figure per batch, each with its engine label.
  - **C8:** "with-camera track blocked K of N".
- Refresh the stale statuses (C7, C10 and others) from the code.

**`eval/claims.yaml`:** for each claim: id, the exact README sentence with `{placeholders}`, the tests that must pass, the result keys, `batch: p1|2|p2|plan|tests`, and the engine label.

**`eval/claims_audit.py`:**
- Runs the tests.
- Renders each sentence from the results.
- Fails on a missing test or key, or on any README sentence that differs from its rendered form.
- Prints PASSING or NOT PASSING per claim.

**Rule:** anything NOT PASSING at 10:00 Nov 4 is **deleted** from the README, video and form.

### P3-1 Scoring and baselines
**`eval/score.py`, per batch:**
- Opens the seal and verifies `sha256(salt‖manifest)`.
- Labels each episode from truth as one of three classes:
  - **unsafe** (above hazard limits);
  - **fault, below hazard limits**;
  - **clean**.
  The label text "fault-but-safe" is banned.
- Reports:
  - dangerous misses;
  - missed faults;
  - false blocks (each with a Wilson 95 % CI; 0/n is shown as "upper bound ≈ 3/n");
  - time to block;
  - severity at release;
  - hold detection by leak-size bin **as counts** (n ≤ 5 per bin, so no rates);
  - INVALID rate;
  - camera vs data-only (batch 2);
  - a per-scenario table.
- Output: `eval/results/score_<batch>.{json,md}`.
- The never-say check runs over every output.

**Baselines (`eval/baselines/`), run on both batches:**
- **Gauge rule:** pass when pressure < 150 kPa and flows ≈ 0 at the last step mark.
- **Muse Spark alone:** the plan plus a downsampled series, one call per episode, temperature 0.

**Reproducibility:**
- Episode bundles include the downsampled signals the baselines use.
- `meta.json` carries the SHA-256 of the full local `signals.jsonl`.
- Manifest and salt are published after scoring.

**Run:** p1 on Nov 3 morning; batch 2 (and p2) as each finishes.

### P3-2 API: contract additions, wiring, replay mode
**First, one API.md + BUNDLE.md commit (Nov 3 08:00), adding what the console needs:**
- **Sessions:**
  - `GET /api/sessions` (list);
  - `POST /api/sessions` (start on a confirmed plan, live mode only);
  - `GET /api/sessions/{id}` including the **plan, steps, who marked and who verified each step, assumptions, plan-check override text, and both verdict tracks**;
  - the SSE stream adds `session_start`, `step_verify`, `step_reopen`, `signature` and camera events.
- **Finding ids:** `<eval_id>:<rule_id>`, stable and used by explain citations and UI links.
- **Camera:**
  - `GET /api/sessions/{id}/camera/{eval_id}` returns the frame, SAM box, crop, Muse Spark reading, and the feedback value it was compared with.
  - Core change: the camera code saves each evaluated frame and crop to `/data/frames/<session>/` (JPEG, about 50 KB), named by the logged hash.
  - **This must land, and pass the image-build gate, before `bench-freeze-2`**, so the demo engine is the batch 2 engine. Otherwise the video says "camera evidence panel added after the benchmark".
- **Voice:**
  - `POST /api/voice/command` accepts `{audio}` **or** `{transcript, asr: "<model id>"}`.
  - Intents: `step_done k`, `confirm`, `cancel`, `status`, `why`, `repeat`, `unknown`.
  - It returns read-back text and never acts.
- **Replay mode (lab-free, no key):**
  - `zs api --replay <bundle_dir>` serves recorded sessions read-only through the same endpoints. Writes return 409 "replay".
  - It's the README's main "run it" path, the Playwright fixture, and the explain-check harness (explain still needs the key; everything else works without one).

**Wiring:**
- Implement every endpoint.
- The audit log is mounted read-only; human actions go to the inbox.
- Published on **`127.0.0.1:8090` only**.

**Tests:**
- every endpoint against its contract;
- `/sign` can't be reached from voice;
- the API never writes `audit.sqlite`;
- replay mode refuses writes;
- net test: `zs-api` reaches only the proxy.

### P3-3 Operator console (`ui/`, static, served by `zs-api`)
**ISA-101 high-performance HMI:**
- neutral greys;
- colour only for abnormal states;
- text and shape as well as colour;
- units always shown.
- **No green verdict banner.** The verdict states are:
  - **"Evaluating…"** (neutral);
  - **"BLOCKED: …"** (alarm);
  - **"ESCALATED: …"** (warning);
  - **"NO DISCREPANCY FOUND — awaiting sign-off"** (neutral, outlined).

**Screen A: New isolation (intake).**
- Three tabs: Type, Upload, CSV.
- An editable table:
  - "plant default" badges;
  - unclear cells block Confirm;
  - photo and transcript side by side.
- A live plan-check panel.
- A plant view: SVG laid out from the map, work equipment highlighted, open paths in red.
- The **Confirm dialog**: name, role, and "I have reviewed this plan".

**Screen B: Job.**
- A live plant view (command / feedback / flow, with disagreements outlined).
- A steps list showing who marked and who verified each step, with Mark done and Verify (a different entered name). Runner names (`eval-operator`, `eval-verifier`) are shown as **"test harness"**.
- Live evidence charts with the vent and hold windows shaded.
- Two-track verdict banner.
- Findings with raw numbers and **Explain**.
- **A permanent assumptions strip**, e.g. "Positive isolation upstream assumed · plan check overridden: control-valve isolation accepted for live-evidence testbed".
- The **camera evidence panel**, labelled idealised camera.
- **Sign dialog:**
  - On NO DISCREPANCY: "Accept and sign".
  - On BLOCKED or ESCALATED: **"Close — not accepted"**, which records a closing signature with outcome `not_accepted` and never reads as approval.

**Screen C: Explain panel.** Answers cite finding ids as links.

The GRFICS 3D view isn't embedded; it sits in its own window for the video.

**Tests:**
- Playwright against **replay mode** and a **throwaway data dir** (`/tmp/zs-ui-test`) only. It may open the Confirm and Sign dialogs but **never submits them on real `/data`**. Submits happen only against the throwaway dir with the name `playwright-test`.
- The never-say check runs over all rendered text.

### P3-4 Explain (`src/zerostate/llm/explain.py`)
- Input: only the session's findings (with ids), summarised windows and the plan.
- Every answer must cite at least one finding id. An uncited answer is retried once, then a fixed fallback is shown.
- Requests to override or approve get the fixed reply: "I can only explain the evidence; only code decides and only a person signs."
- Tests with a fake client.
- **Measured:** 10 questions on 3 replayed sessions, checked by hand, recorded in MODEL_NOTES. The claim exists only if measured.

### P3-5 Voice walkthrough (D3)
- Push to talk → speech-to-text (Muse if confirmed, otherwise the local Meta open-weights model) → intent → spoken read-back with the browser's `speechSynthesis`. That's speech *output* only, with no model involved.
- Only on `confirm` (voice or click) is the step marked. The live result is then spoken.
- **It never signs, verifies or reopens.**
- **Measured:** the 20 clips through the chosen speech model + intent route. The bar is ≥ 18/20 with 0 wrong-step mappings. Recorded in MODEL_NOTES; `eval/voice_test.py` is committed.

### P3-6 Public results + replay site (`site/`, Vercel)
- Static, with no key and no backend. Data comes from `eval/tools/build_site_data.py` (bundles plus score files).
- **Pages:**
  - **Results per batch:** engine label, CIs, baselines, per-scenario tables, leak-size counts, INVALID rate, seal hashes with verification, known limits.
  - **Episodes:** a filterable list.
  - **Episode replay:** "What ZeroState saw" beside "Simulator internals — not read by ZeroState's data checks".
- **Every number links to its episodes.** Runner names are shown as "test harness".
- **Deploy:**
  - Bhargavi creates the Vercel project at 08:00 Nov 3, with root `site/` and **deployment protection off** for previews.
  - Production deploys from `main`, so schedule the `p3-work` → `main` PR merge for **Nov 4 08:00**.
- **Tests:**
  - the data builder validates every bundle;
  - no key-like strings;
  - every number matches the score files;
  - never-say check.

### P3-7 README and submission text
**README sections:**
1. Problem.
2. What it is and isn't.
3. Architecture.
4. **Results** rendered from `claims.yaml`.
5. A Meta model table (each call site, with measured accuracy).
6. **Run it**:
   - (a) **Replay mode, no lab, no key:** one command on a sample bundle, opens the console.
   - (b) The full lab (Windows + GRFICS + patched image + router script + key), with the confirm step done by a person.
7. Plants tested.
8. Known limits, including: unauthenticated names, idealised camera, noise-model dependence on P1, a solo builder typing the second name.
9. Credits spent.
10. Built-during-event dates (including the Oct 27 kill test).
11. Licences (Apache-2.0 / GPL-3.0 patch / Fortiphyd credit).
12. Built with an AI coding assistant from written specs, if the rules allow.

**Form text:** short description, links, track Indie.

### P3-8 Demo driver and video
- **`eval/tools/demo_driver.py`:**
  - Performs operator actions and injects the chosen fault on cue.
  - **Marks nothing.** The person marks steps in the console or by voice.
  - Captioned in the video: "operator actions and fault injection by test harness; simulator at ×10, footage sped up where noted".
- **Recording:** OBS, 1080p, console plus a separate GRFICS window. 2–3 takes per segment. A failed live take falls back to a **captioned replay of that exact episode**, never a staged screen.

### P3-9 Phase 2 leftovers Phase 3 depends on (must close before `bench-freeze-2`)
- `run_benchmark.py` passes `--camera` per batch entry, with a test. **Batch 2 must not run camera-off by accident.**
- The batch 2 manifest has no P2 entries. P2 gets its own batch (D1).
- `--plant p2` in the runner, `seal.py` batch `p2`, a P2 compose service, 4840 router and allowlist rules, and the operator `p2` command. Only if D1 is a go.
- The frame-saving core change (P3-2).
- Image-build gate passes on the freeze commit.
- STRUCTURE.md refreshed to the real file list.
- `PHASE_2_GATE.md` written, so Phase 2 is formally gated.
- **Batch 2 runs with no watchdog skipping**, so S0 ×15 stays whole.

## Nov 3 lab queue (one thing at a time)

| Time | Lab job | Done when |
|---|---|---|
| 07:00 | Check batch p1 finished (log, progress, INVALID count). If not, let it finish before anything below | p1 complete |
| 07:30 | Image build gate on `p2-work`; first live Muse Spark + SAM call through the proxy | both succeed; credits logged |
| 08:00–10:30 | **Camera:** headless render → choose view → measure display regions → measure lag | reads on 3 test frames match truth |
| 10:30–12:00 | Frames set (C7, 100 frames) | `read_accuracy.py` output committed · **12:00 camera go/no-go (D2)** |
| 12:00–13:00 | Importer accuracy run (C14), live model calls, no Docker plant needed. Voice clips through the speech model (D3) | results in MODEL_NOTES · **13:00 voice go/no-go** |
| 13:00–17:30 | P2 live: compose service, rules, operator, runner smoke (S0×3, S1, S4-small, S10, S11) and threshold tuning on tuning seeds | smoke matches · **18:00 P2 go/no-go (D1)** |
| 17:30–19:30 | Full-engine smoke on final code (P1 S0×2, S7, S13, S8 with camera); `pytest -m net`; Bhargavi confirms the plans | all match |
| 19:30–20:00 | Build gate → `bench-freeze-2` → seal 2 (and p2) → launch | ≥ 1 valid scoring episode |
| 20:00–~01:30 | Batch 2 (~2.6 h), then batch p2 if go (~2.5 h) | complete |

**Overnight:** phone alarms at 23:00 and 01:00 to check `progress.jsonl`. If a batch stops after 3 INVALIDs, fix the lab and re-run the same command; it resumes.

## Schedule (agents, offline)
| When | Work |
|---|---|
| Nov 3 08:00–13:00 | P3-0 · P3-1 (score p1) · P3-2 contract commit, then wiring + replay mode · P3-3 screens A/B |
| Nov 3 13:00–20:00 | P3-3 continued · P3-4 · P3-6 · P3-5 (if voice go) · P3-9 leftovers |
| Nov 4 01:30–09:00 | Score batches 2 and p2 · baselines · build site data |
| Nov 4 08:00 | PR `p3-work` → `main` → Vercel production |
| Nov 4 10:00 | **Claims audit** |
| Nov 4 10:00–14:00 | README · **record the video** |
| Nov 4 14:00–18:00 | Edit · form · fresh-clone replay check · **submit** |

## Gate (`docs/specs/PHASE_3_GATE.md`)
1. `claims_audit.py` output: every claim used is PASSING; the others are deleted.
2. All seals verified; score files committed.
3. Vercel results page live (no login wall); numbers match the score files; never-say check clean.
4. Console Playwright passes on replay mode and the throwaway dir. `/sign` is unreachable from voice. No `\bsafe\b` anywhere.
5. Net tests: `zs-api` reaches the proxy only, and earlier boundaries still hold. Port published on 127.0.0.1 only (`docker port zs-api` output).
6. **Fresh clone → replay mode → console with a recorded session**, in under 5 minutes, with no lab and no key.
7. Video within the length limit; every on-screen number PASSING; all captions present.
8. Submitted; confirmation screenshot saved in `docs/`.

---

# Demo storyboard (≤ 3:00; adjust after the participant-guide check)

**Spine:** *"Before anyone opens a pipe, someone has to prove it's dead. ZeroState is a second check that can only say no, and shows its work."*

| Time | Screen | Voiceover | Proves |
|---|---|---|---|
| 0:00–0:15 | Text only: isolation failures (LyondellBasell 2021: the valve relied on was the one being worked on; LOTO is OSHA's 4th most-cited standard), CSB cited | "People die in the step where someone proves equipment is isolated." | Impact |
| 0:15–0:30 | Architecture frame: plant → read-only → ZeroState → person signs | "ZeroState reads the plant, can't write to it, and never approves. A person decides." | Safety design |
| 0:30–1:00 | **Intake on the P2 gas-line map** (captioned "synthetic map" if P2 was cut): type the isolation in words → Muse Spark fills the table → plan check flags **a wrong-tag point on the adjacent line** (PC5) → fix → clear → Bhargavi confirms | "The planner writes it in words. ZeroState checks it against the plant before anyone touches a valve." | Muse Spark, plan checks |
| 1:00–1:40 | Caption: "Live job on the GRFICS reactor (benchmark plan)". Console + 3D window. Voice or click marks steps → read-back → **step check: PASS**. Then a passing valve below the flowmeter cutoff → the hold rises → **BLOCKED**. "Why?" → explain cites the finding | "The flowmeter reads zero. The hold test shows a rise of <N> kPa." (real number from the take) | Live checks, explain, voice (if go) |
| 1:40–2:05 | (If camera go) The instrument says closed; the **idealised camera** panel shows SAM 3.1's box, the crop and Muse Spark's reading of open → with-camera track **BLOCKED** | "The instrument says closed. An independent view disagrees." | SAM 3.1, independent channel |
| 2:05–2:40 | Vercel results: sealed batches with engine labels, dangerous misses with CI, false blocks, vs gauge rule and Muse Spark alone → one episode replay, "what ZeroState saw" vs simulator internals. Gas line on OPC UA if batch p2 ran | "Pre-registered, sealed, replayable — every number links to its episodes." | Whether it works |
| 2:40–3:00 | Repo + replay-mode command + limits line | "Not safety-rated. Not a replacement for proving dead. A second check that can only say no." | Honesty |

**Video rules:**
- Every on-screen number is PASSING.
- No line implies prevention of a named incident.
- Captions name the test harness, ×10 speed-ups, the idealised camera, and any replay fallback.
- The verdict banner is never green.
