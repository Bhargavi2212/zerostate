# Phase 2: Product breadth + the overnight benchmark (spec)

Goal: by 22:00 tonight, ZeroState does four new things, and the pre-registered benchmark is running:
1. It checks **isolation plans** against a plant graph, before anyone acts.
2. It **imports plans three ways**: typed text, a photo/PDF of an isolation sheet, or a SAP/Maximo-style CSV. A person always confirms the result.
3. It **reads the plant camera** with SAM 3.1 + Muse Spark.
4. It runs on a **second live plant** (the gas line, OPC UA), if that plant is running by 18:00.

Process checks are also added. Every model call goes through one egress proxy that can only reach the Meta API.

- **Branch:** `p2-work` (use parallel worktrees for independent items; see Schedule). **Tag:** `phase-2` after the gate. **Freeze tag:** `bench-freeze`.
- **Built in Phase 3, contract fixed here (P2-9):**
  - the operator console (plant view, intake screen with three tabs and an editable table, live evidence, sign-off);
  - the explain-only chat;
  - the voice walkthrough;
  - the public replay viewer + results page **on Vercel**;
  - claims tooling.

  Phase 2 defines the API and data contracts these need and builds the episode-bundle export, so Phase 3 is UI work only, not backend redesign.

## Facts and decisions carried in
- **Time base.** P1 runs at ×10. Isolation episodes run with the PLC in manual mode. The vent fidelity check (×10 vs ×1, aligned on 2500 kPa) agrees within 1 %.
- **P1 plan.** Block-in plan, hash committed. Vent start is 1826–2411 kPa; **a start below 1500 kPa marks the episode INVALID**. `hold_max_rise_kpa: 1.0`. LIVE-QUALITY v2, LIVE-HOLD v2.
- **Meta API** (confirmed by the Oct 27 kill test):
  - Base URL `https://api.meta.ai/v1`.
  - `muse-spark-1.3` via `POST /chat/completions`, OpenAI-style messages, images as `data:` URLs.
  - `sam-3.1` via `POST /responses` with `stream: true` and `metadata.include_confidence: "true"`. The text prompt and `input_image` go in one user message. Boxes stream as `response.output_text.delta` text containing `<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..;c=..|>`.
  - SAM 3.1 found tanks (~0.94) and digital displays (~0.8), but **zero "valve" objects**.
- **Truth.** P1 truth is read **inside** the simulation container (Docker VM clock). The Windows localhost:80 forward is not used by anything automated.
- **Firewall.** ZeroState lives in `zerostate-net`'s namespace. Its OUTPUT allowlist currently allows only lo, ESTABLISHED and 192.168.95.2:502. Every new destination in this phase is added there **and** gets a net test.
- **Owner decisions:**
  - All three intake routes (typed text, upload, CSV) are required.
  - The person authors the plan; Muse Spark only structures it.
  - Voice: transcription test now, walkthrough in Phase 3.
  - Tag-plate confirmation is a stretch item.
  - The live gas line has a hard cutoff at 18:00.
  - The benchmark launches by 22:00.
  - Console centerpiece: a plant view drawn from the map data, with work equipment highlighted, energy paths traced and open paths in red.
  - Explain chat answers from logged findings only and never changes a verdict.
  - Voice: fixed command set, every mark read back, never signs.
  - The public replay viewer is hosted on **Vercel** (static). Nothing live is hosted publicly: the lab stays on the local machine.
- **New decision in this spec:**
  - **No model judge in the gate.** No model output ever feeds a verdict, so the safety path is code only.
  - C10's wording changes from "the model can only add a block" to **"no model output feeds any verdict"**.
  - `llm/judge.py` is removed from STRUCTURE.

## Cut order (if the day runs short, in this order)
0. **P2-10 tag-plate** (stretch).
1. **P2 live plant** (item P2-6). If it isn't running and passing its own smoke by **18:00**, cut it. P2's plant map stays as the plan-check substrate, labelled "synthetic map". C2 and C12 are withdrawn.
2. **PROC-RESET** (item P2-7c), moved to Phase 3 morning.
3. **PROC-INDEPENDENCE** (item P2-7b), moved to Phase 3 morning.

**Never cut:** the proxy, plan checks, the importer (all three routes), the camera, PROC-SEQUENCE, the P2-9 contracts and bundle export, and the P1 benchmark launch.

## Items

### P2-0 Doc alignment (first commit)
- **PROJECT / ARCHITECTURE:**
  - No model judge; update the C10 wording.
  - Egress proxy and `zs-internal` network.
  - Frame service.
  - The plan is the plant map plus an isolation list (P2-3).
  - The OPC UA read-only proof is server-enforced (P2-6).
- **STRUCTURE:**
  - Add `docs/API.md`, `docs/BUNDLE.md`, `src/zerostate/api/` (server, routes), `deploy/api_net.sh`, `site/` (Vercel viewer, Phase 3), `eval/tools/export_bundle.py`.
  - Add `deploy/proxy/`, `plants/frame_service/`, `plants/p2_gasline/*`, `src/zerostate/adapters/opcua.py`, `src/zerostate/importers/*`, `src/zerostate/llm/client.py`, `src/zerostate/graph/*`, `src/zerostate/checks/plan/*`, `src/zerostate/checks/process/*`, `eval/sealed_hash.txt`, `eval/baselines/*`, `eval/importer_set/`, `eval/frames_set/` (hash only).
  - Remove `llm/judge.py`.
- **EVAL:**
  - Benchmark counts (P2-8).
  - The "missed fault" vs "dangerous miss" distinction (P2-8).
  - Camera results come from the same episodes, with data-only verdicts produced by replay.
- **DECISIONS:** one row per new decision above.

### P2-1 Egress proxy, model client, credit ledger
**Network:**
- New Docker network `zs-internal` (`internal: true`, subnet 172.30.0.0/24, **no internet**). Members:
  - `zerostate-net` at .10 (ZeroState's namespace);
  - `zs-proxy` at .2;
  - `zs-frames` at .3 (P2-4).
- New bridge `zs-uplink` with internet; only `zs-proxy` joins it.

**Proxy:**
- `deploy/proxy/`: tinyproxy, the smallest maintained option.
- `FilterDefaultDeny Yes`, with a filter allowing only `^api\.meta\.ai$`.
- `ConnectPort 443` only; listen on 8888.
- TLS stays end to end (CONNECT tunnel), so the proxy never sees the key or the content.

**ZeroState allowlist:** `net_setup.sh` adds 172.30.0.2:8888 (proxy) and 172.30.0.3:8080 (frames).

**Model client (`src/zerostate/llm/client.py`)** is the only module allowed to call the Meta API.
- Uses `HTTPS_PROXY=http://172.30.0.2:8888`.
- The key comes from env `MODEL_API_KEY`. In compose, the variable name is listed without a value, so Docker takes it from the host environment. It is never logged, printed or written.
- Functions:
  - `spark_json(messages, schema)`: Muse Spark, strict-JSON reply validated with pydantic, one retry on invalid JSON, then raise;
  - `sam_boxes(image_bytes, prompt)`: parse `<|box…|>` tokens into box + confidence.
- Every call appends one line to `/data/credits.jsonl`: ts, model, purpose, input/output tokens or image count, estimated $. Pricing: Spark $1.25 / $4.25 per M tokens; SAM ≈ $2.50 / 1k images.
- **Budget guard:** env `ZS_BUDGET_USD` (default 75, about half the ~$150 of credits; this phase is estimated at $6–9). It isn't a spending limit for normal work, only a stop for a runaway loop. The client refuses calls once the ledger total passes it, and the value can be raised in the env at any time.

**Host tool:** `eval/tools/credits_report.py` copies the container ledger out with `docker cp` and appends a dated summary to `D:\grfics\credits_log.md`.

**Tests:**
- `tests/test_llm_client.py`, offline with a fake transport:
  - box-token parsing;
  - strict-JSON retry, then failure;
  - ledger line written;
  - budget refusal;
  - the key never appears in any log or exception text.
- `tests/net/` additions, run inside ZeroState:
  - CONNECT `api.meta.ai:443` via the proxy succeeds (TCP plus a TLS handshake; no API call);
  - CONNECT `example.com:443` → 403;
  - CONNECT `host.docker.internal:80` → 403;
  - direct `1.1.1.1:443` → fails;
  - 172.30.0.3:8080 reachable.
- `tests/test_firewall.py`: only `llm/client.py` may reference `api.meta.ai`; only `llm/` may import an HTTP client.

### P2-2 Plant graph and plan checks (`src/zerostate/graph/`, `src/zerostate/checks/plan/`)
**Model split (the plan = plant map + isolation list):**
- **Plant map** (`plants/<p>/plant_map.yaml`, data):
  - Nodes: `source` (with energy type and pressure), `vessel`/`segment`, `valve` (with `device: block_valve | control_valve | check_valve`, `actuation: manual | actuated`, `normal_state`), `vent`/`bleed` (with `discharges_to: atmosphere | flare | header:<id>`), `relief`, `heater`, `instrument` (with role, side, signal_ref).
  - Edges: pipes.
- **IsolationList** (authored by the person; the importer's output): `work_equipment`, `points[{tag, required_state, seq, isolation_type: positive|proved|non_proved}]`, `vent {tag}`, `proving [{tag, proves:[tags]}]`, `hold_minutes`.
- **`graph/build.py`** merges the map and the list into the existing frozen `IsolationPlan` (steps, witnesses, relations derived from the map). It is deterministic, so the same inputs always give the same plan hash.

**Plan rules** (pure functions `check(plan, graph, params) -> Finding`, with `RULE_ID` / `RULE_VERSION`):

| Rule | Fails when |
|---|---|
| PLAN-PATHS | With every listed point in its required state, any `source` still has a path to `work_equipment`. The message names the path. |
| PLAN-LIVESIDE | A listed isolation device is itself inside the energised region, i.e. reachable from a source without crossing another closed listed point (the LyondellBasell pattern). |
| PLAN-BOXEDIN | The isolated region contains a `heater` (or other heat source) and no open vent/relief path to atmosphere or flare (Williams). |
| PLAN-SOFTWARE | A listed point is a `control_valve` with `actuation: actuated` and no positive isolation behind it, i.e. isolation relies on a control system command (OSHA 1910.147(b), HSG253 case). |
| PLAN-TYPE | Hazardous service (from source data) is isolated only by `non_proved` points. |
| PLAN-PROVING | A `proved` point has no proving point, or its bleed `discharges_to` a header that is itself a source/pressurised (IChemE LPB 250). |
| PLAN-MAPPING | A tag in the list isn't in the map, an instrument witness sits on the wrong side, or `work_equipment` doesn't exist (the Pemex/Formosa pattern at plan level). |

- **Expected for P1's real plan:** BLOCKED by PLAN-SOFTWARE (all four are actuated control valves) and PLAN-TYPE. This is correct and shown in the demo.
- **Live episodes on P1** run with `--plan-check-override "control-valve isolation accepted for live-evidence testbed"`, which is logged in `session_start` and printed with every verdict. Without the override, a P1 session refuses to start past the plan check.
- **Tests:** `tests/checks/test_<rule>.py` for each rule, with one PASS and one FAIL using small hand-built graphs.

**Plan-check set (`eval/plan_cases/`):**
- `make_cases.py` builds cases from the **P2 map** by mutating the correct IsolationList. Seeds come from the tuning range for development and from the sealed manifest for scoring.
- PC0 correct; PC1 drop a point; PC2 choose a live-side device; PC3 add heater + no relief; PC4 swap a block valve for an actuated control valve; PC5 wrong tag (adjacent line); PC6 remove the proving point / bleed into a header.
- Labels are written by the generator **before** the checks run.
- `eval/plan_benchmark.py` → `eval/results/plan_<date>.json`.

### P2-3 Importer: three routes, one confirm (`src/zerostate/importers/`)
- **`csv_import.py`** (no model). Columns: `work_order, equipment, tag, required_state, apply_seq, isolation_type, lock_id, vent_tag, proving_tag, proves`. Exact parse, any error raised. This is the shape of a SAP WCM / Maximo isolation export.
- **`text_import.py`** (typed chat): free text → `spark_json` → `IsolationList`. The prompt includes the plant map's tag list so names can be matched, and it says plainly: *"extract only what the author wrote; never add a point; mark anything unclear as `null` with a note."*
- **`image_import.py`** (photo/PDF): image, or the first page of a PDF rendered with `pypdfium2`, → `spark_json` with the same schema and rules.
- **All three** produce a **draft** saved to `/data/drafts/<id>.json`, then:
  - `graph/build.py` merges it with the map;
  - the **plan checks run immediately** on the draft;
  - unresolved `null`s → the draft cannot be confirmed.
- **`confirm.py`:** `zs plan confirm <draft> --by <name> --role issuer` freezes the plan and prints its hash. `zs session start` refuses any unconfirmed plan (it already checks `--plan-hash`).
- **CLI:** `zs plan import --csv|--text|--image <path>`, `zs plan show <draft>`, `zs plan confirm`.

**Accuracy set (C14), `eval/importer_set/`:**
- 12 cases with gold `IsolationList`s, **committed before the importer is ever run**:
  - 6 typed texts in the style a planner would write, for P1 and P2 jobs;
  - 6 sheet images in the field layouts of public procedures (Seqwater, NPDC, Marathon), rendered from our own filled templates with no real company names or logos;
  - including 2 with an ambiguity that must come back `null`.
- `eval/importer_accuracy.py`: field-level precision and recall per route, plus the count of invented points, which must be 0.
- **State it plainly:** "authored by us, n = 12".

**Tests:**
- `tests/test_importer_gate.py`: unconfirmed draft → session refuses; a draft with nulls can't be confirmed; CSV parse errors raise.
- Text and image routes are tested offline with a fake client.

### P2-4 Camera channel (frame service + LIVE-CAMERA)
**Frame service (`plants/frame_service/`, container `zs-frames`):**
- Runs headless Chromium (Playwright Python image).
- Networks: `a-grfics-admin`, to reach `http://simulation/` without touching the Windows port forward, and `zs-internal` (172.30.0.3).
- `GET /frame?view=<name>` returns a JPEG (quality 70, plus light Gaussian noise σ = 3 grey levels) and a capture timestamp. **Nothing else is served.**
- For eval only, each capture also writes a truth sidecar (from `/data/index.php` at the same moment) to a volume that ZeroState never mounts. The runner copies it out with `docker cp`.
- On P1 it renders truth by construction, so it is labelled "idealised camera" everywhere.

**Viewpoints (first task; stop and report if it fails):**
- Confirm the Unity WebGL scene renders in headless Chromium (software GL).
- Find a fixed view showing the **f1** display, and ideally purge and product too. Use the default camera, or a scripted key/mouse sequence stored as `views.yaml`.
- Write `display_map.yaml`: view → display box region → valve tag.
- If f1 can't be shown, LIVE-CAMERA covers whichever valves are visible, and S8 relies on VALVE alone. Record that.

**Reading pipeline (`src/zerostate/camera/`):**
- `client.py`: fetch a frame through the allowlisted 172.30.0.3:8080.
- `locate.py`: `sam_boxes(frame, "digital display")`, matched to `display_map` regions by overlap.
- `read.py`: crop with 15 % padding, upscale ×3, then `spark_json` returns `{value: number|null, readable: bool}`. A **single read** (3-read voting is a should).
- `freeze.py`: a pixel hash of each display crop across successive captures. An unchanged crop while the Modbus feedback has changed beyond the lag window → "display frozen". This is code, never the model.

**LIVE-CAMERA rule (`checks/live/camera.py`, pure, over logged readings):**
- Runs at each valve step after settle, on each valve with a mapped display.
- Capture 3 frames 2 s wall apart.
- **PASS:** some reading agrees with the Modbus feedback (±5 %) at a time within `[t − camera_lag_max_wall_s, t]`.
- **FAIL:** all readable frames disagree with every feedback value in the window: "camera shows X % while the instrument says Y %".
- **UNKNOWN:** fewer than 2 readable frames.
- `camera_lag_max_wall_s` is **measured**: [Likely] the Unity page polls every 3 s, so start at 5 and confirm against truth sidecars.

**Config.**
- Plans declare `camera: optional | required`. P1 is `optional`.
- The runner runs P1 benchmark episodes with the camera **on**.
- The headline **data-only** verdicts come from `zs replay --disable LIVE-CAMERA` on the same episodes. One run gives both systems.
- Camera evaluations are logged as their own events, so this replay works.

**Accuracy set (C7), `eval/frames_set/`:**
- 100 frames. The operator sets valves to random positions on the lab in manual mode (tuning lab session, not scoring).
- Labels come from the truth sidecars. Store the frames outside git; commit only their hash list.
- `eval/read_accuracy.py`: exact match within ±1 %, within ±5 %, `unreadable` rate, and per-valve breakdown.
- **Cost:** about 100 × (1 SAM image + 1 Spark read) ≈ $0.5.

**Tests:** offline with fake client and fixture images: region matching, `unreadable` handling, freeze detection, and PASS/FAIL/UNKNOWN for LIVE-CAMERA from synthetic logged readings.

### P2-5 Voice transcription test (no product code yet)
1. **Find, don't guess:** look up Muse Voice Transcribe's model ID and endpoint in the Meta developer docs and record the URL in MODEL_NOTES. If it can't be found or called with our key, stop this item. Phase 3 voice then uses the browser's speech recognition, labelled as such.
2. **Recordings:** 20 short clips recorded by Bhargavi (laptop mic, normal room, a few with a fan or background noise), covering the fixed command set: "feed one closed", "purge open", "status", "why", "repeat", step numbers. Store them outside git; commit only the expected intents.
3. `eval/voice_test.py`: transcribe → `spark_json` maps to the command set or `unknown` → intent accuracy.
   - **Bar:** ≥ 18/20 correct, 0 wrong-step mappings ("unknown" is acceptable; a wrong step is not).
   - **Cost:** cents.
   - Result → MODEL_NOTES and DECISIONS.

### P2-6 P2 gas line, live (hard cutoff 18:00)
**Spec first** (`plants/p2_gasline/SPEC.md`, committed before any code):
- **Gas:** nitrogen, isothermal 293 K, R = 8.314 kPa·m³/(kmol·K), atmosphere 101 kPa abs.
- **Equipment:**
  - Supply header **S-200**: constant 2000 kPa abs, a boundary source.
  - Upstream double block and bleed: **XV-201** (block 1), cavity **C-202** (V = 0.05 m³) with bleed **BV-202** to atmosphere, **XV-203** (block 2).
  - Work vessel **F-210** (filter, V = 2.0 m³) with:
    - **PT-211** and **PT-212**, redundant pressure transmitters, 0–2500 kPa;
    - vent **VV-213** to atmosphere, with flow meter **FT-213**;
    - relief **PSV-214** to flare, set at 2300;
    - electric heater **E-215**, off by default.
  - Downstream block **XV-204** to consumer header **D-220**: constant 1500 kPa abs, a second source (backflow).
  - Adjacent line **L-230** with block **XV-231**. It's the decoy for the wrong-valve scenario, the Pemex pattern.
  - **PT-200:** header pressure, upstream of XV-201.
  - **PT-202:** cavity pressure.
- **Valves:**
  - Manual block valves, each with an actuated remote command for the sim operator.
  - Position feedback from limit switches: 0 or 100, with the same fault modes as P1 (frozen, offset, fixed).
  - Travel time 10 process-s.
  - `leak_pct` same as P1.
- **Flow law between two volumes:** `F = Cv · x/100 · sqrt(max(P_up² − P_dn², 0))` in kmol/h, with each volume integrated as `dn/dt = ΣF`, `P = nRT/V`. Cv values are chosen so venting F-210 from 2000 kPa to 102 kPa through VV-213 takes about 5 process-min.
- **Analytic check (C12, implementation check):** for a vent to atmosphere, `dP/dt = −(RT·Cv/(100·V))·x·sqrt(P² − Pa²)` gives exactly `P(t) = Pa·cosh(acosh(P0/Pa) − a·t)`.
- **Instruments:** noise ±0.1 % of span on every analog value. Faults on any transmitter: frozen, drift (signed), dropout, plus the valve feedback faults.
- **Time scale:** ×30 (no PLC loops to destabilise), integrator step ≤ 1.5 process-s. C12 must pass at ×30.

**Implementation:**
- `model.py`: physics, pure and testable.
- `server.py`: asyncua OPC UA server at `opc.tcp://192.168.95.50:4840`, on `b-ics-net`. Confirm the IP is free first.
  - Nodes `ns=2;s=<TAG>.PV` (instruments), `<VALVE>.FB` (feedback), `<VALVE>.CMD` (command).
  - Good StatusCode and SourceTimestamp on every value.
  - **Users:**
    - `zerostate`: read-only, enforced by the server's permission check;
    - `operator`: may write `*.CMD` only.
  - Every write attempt is logged with its user to `/var/log/p2_writes.jsonl` inside the container.
- `faults.py` and `truth.py`: run via `docker exec -i p2 …` against a local unix socket. Never on the network.
- `envelope` = `plant_map.yaml` + `isolation_list.yaml`.
- **Correct P2 plan steps:**
  1. Close XV-201.
  2. Close XV-203.
  3. Open BV-202 (bleed; PT-202 must fall to atmospheric and stay there, which proves XV-201 holds).
  4. Close XV-204.
  5. Vent F-210 via VV-213 to `vent_target_kpa_abs: 102`.
  6. Close VV-213.
  7. Hold 600 process-s:
     - PT-211/212 show no rise;
     - PT-202 stays atmospheric with the bleed open;
     - PT-200 ≥ `upstream_min` (1500 kPa) the whole time.
  8. Final.

**Operator for P2:** the existing `zs-operator` container gains `asyncua` and a `p2` sub-command (`set <valve> open|closed`, `status`, `wait-pressure-below`), logging in as the `operator` user. Router rule .70 → .50:4840.

**P2 thresholds** (`plants/p2_gasline/thresholds.yaml`) are tuned on P2 tuning seeds, **not copied from P1**:
- There's no reaction, so clean holds should be flat.
- Set `hold_max_rise_kpa` at about 3× the measured window-mean noise.
- Pick `window_process_s` so each window has ≥ 16 samples at ×30. At 4 Hz polling that's ≥ 120 process-s.

**ZeroState side:**
- `adapters/opcua.py`: asyncua client, read-only user, uses `read_values` only. Quality comes from the StatusCode, and **freshness from SourceTimestamp**: older than `max_age_wall_s` → STALE, on top of the noise rule.
- Router rules: .60 → .50:4840 and .70 → .50:4840. `net_setup.sh` adds 192.168.95.50:4840.
- New relation types (data, generic):
  - `redundant_pair`: PT-211 vs PT-212 within tolerance;
  - `valve_flow_gas`: FT-213 vs the vent law from PT-211/212.
  - LIVE-RELATION votes 2-of-3 when three estimates exist.
- New rule **LIVE-UPSTREAM** (`checks/live/upstream.py`): during the hold, the upstream witness must stay ≥ `upstream_min`, otherwise UNKNOWN: "hold test meaningless: no pressure behind the isolation" (S11).
- **C1 for OPC UA:** the IDS can't parse OPC UA, so the read-only evidence is the server's own enforcement plus `p2_writes.jsonl` showing **0 write attempts by `zerostate`** in every episode. The runner postflight checks this.

**P2 scenarios (`eval/scenarios/p2/`):**

| ID | Fault |
|---|---|
| S0 | clean |
| S1 | PT-211 frozen during the vent → RELATION (pair + vent law) |
| S1b | PT-211 **and** PT-212 frozen after the vent, plus XV-203 leak 0.3–1.5 % |
| S2 | dropout |
| S3 | PT-211 drift low |
| S4-small / S4-large | XV-204 leak (backflow) |
| S5 | operator closes XV-231 instead of XV-204 |
| S7 | step skipped / installer = verifier (needs P2-7) |
| S8 | XV-204 feedback reads closed, valve stuck open. There's no flow meter on that line, so the expected catch is backflow from D-220 seen by ALIVE (the vent never reaches target) or HOLD. Expected: not NO_DISCREPANCY |
| S10 | VV-213 blocked (flow scale 0) → ALIVE FAIL |
| S11 | S-200 depressurised during the hold → UPSTREAM UNKNOWN |
| S12 | OPC UA server stops updating → STALE by timestamp |

**P2 smoke before 18:00:** S0 ×3, S1, S4-small, S10, S11, all matching expectations, plus C12 passing. **If any of this is missing at 18:00, cut P2-6** (see the cut order).

**Unsafe definition for P2 (EVAL):** true F-210 pressure > 150 kPa abs, or true flow into F-210 > 1 % of Cv at the hold end, at the moment of NO_DISCREPANCY.

### P2-7 Process checks (`src/zerostate/checks/process/`)
- **a. PROC-SEQUENCE (never cut).** Step marks must come in plan order, each only after the previous step's evaluation. Out of order or skipped → FAIL "step k marked before step j was verified".
- **b. PROC-INDEPENDENCE (cut second).**
  - Each `isolate` step needs a `zs step verify <s> <k> --by <name>` from a **different** person than the one who marked it done. Same person → FAIL. Missing at final → UNKNOWN.
  - The runner uses two operator names. S7 uses the same name, or skips a step.
- **c. PROC-RESET (cut first).**
  - `zs step reopen <s> <k> --by --reason`, for "inch and test", sets the affected points back to pending.
  - Steps that depend on them are re-evaluated. A final verdict needs them to pass again.
  - New scenario S13: reopen f1 for a test, close it again, and the runner **doesn't** re-verify → no NO_DISCREPANCY.
- **Tests:** one PASS + FAIL per rule. Session tests for verify and reopen.

### P2-8 Benchmark freeze, seal, launch (by 22:00)
1. **Freeze.**
   - All rules, thresholds and both plans committed.
   - `bench-freeze` tag pushed.
   - The runner refuses scoring seeds unless HEAD == `bench-freeze`, the tree is clean, and the plan hash equals the frozen plan.
2. **Seal** (`eval/seal.py`):
   - Draws scoring seeds (≥ 10000) from `os.urandom` for each (plant, scenario, n).
   - Writes the manifest and a random salt **outside the repo** (`D:\grfics\sealed\`).
   - Commits only `eval/sealed_hash.txt = sha256(salt ‖ manifest)`, **before** the first scoring episode.
   - The manifest order is shuffled, so scenarios interleave and slow lab drift can't line up with one scenario.
3. **Counts:**
   - **P1:** S0 × 15, plus S1, S1b, S2, S3, S4-small, S4-large, S5, S6, S7, S8, S12 × 5 each = **70 episodes**, ≈ 7–8 h at ×10.
     - If PROC-RESET was built, add S13 × 5 (+35 min).
     - If PROC-INDEPENDENCE was cut, S7 tests only the skipped step (PROC-SEQUENCE). Say so in the results.
   - **P2, if not cut:** S0 × 15 plus 12 fault scenarios × 5 = **75 episodes**, ≈ 2 h at ×30.
   - **Plan set:** PC0 × 15, PC1–PC6 × 5 = **45 cases**, seconds.
4. **Run** (`eval/run_benchmark.py`):
   - Resumable: skips episodes that are already complete.
   - An invalid episode (pre/postflight, guard, fault not applied, vent start < 1500) is retried once with the same seed. If still invalid it's recorded INVALID and not counted. **The INVALID rate is reported.**
   - Order: plan set, then P2, then P1.
   - **Watchdog at 05:00:** if the projected finish is after 09:00, skip the remaining P1 S0 beyond 10, logged.
5. **Next morning (Phase 3, not tonight):**
   - Baselines on the recorded `signals.jsonl`:
     - gauge rule (offline, free);
     - Muse Spark alone: a downsampled series plus the plan, one call per episode, ≈ $2–3.
   - `score.py`:
     - **dangerous misses** (truth unsafe and NO_DISCREPANCY) with Wilson 95 % CI;
     - **missed faults** (fault present, truth safe, NO_DISCREPANCY), reported separately;
     - **false blocks** (clean, not NO_DISCREPANCY);
     - time to block;
     - severity at release;
     - LIVE-HOLD detection rate by leak size;
     - camera vs data-only.
   - Then open the seal and publish the manifest and salt.

**Budget for the whole phase:** about $6–9 (camera reads in 70 P1 episodes ≈ $3–4, frames set $0.5, importer set + dev $1, voice cents, baselines next morning $2–3). `ZS_BUDGET_USD=75` stops only a runaway loop. Update `D:\grfics\credits_log.md` after each live session.

**Episode bundles for the replay viewer:**
- Every scoring episode writes `eval/results/bench/<episode>/`:
  - `bundle.json.gz` (P2-9 schema);
  - `verdict.json`;
  - `meta.json`;
  - `ids.json` (P1) or `p2_writes.json` (P2).
- Bundles are committed after scoring.
- [Likely] About 150 episodes × ~150 KB gzipped ≈ 25 MB. If the total goes over 50 MB, downsample signals to 1 Hz in the bundle; the full `signals.jsonl` stays local and its hash goes in `meta.json`.

### P2-9 Frontend, voice and deployment contracts (small code; the UI itself is Phase 3)
Fixed now so Phase 3 builds against a stable backend.

**Where things run:**

| Piece | Runs | Reaches |
|---|---|---|
| ZeroState core (monitor, checks, audit) | `zerostate` (no inbound ports) | PLC, P2 OPC UA, proxy, frames |
| **API** (`zs-api`, same image, `zs api` command, FastAPI) | own container, port **8090 published to Windows**, its own `zs-api-net` helper with an OUTPUT allowlist: proxy only | `zs-data` volume (audit **read-only**, inbox and drafts read-write), proxy (importer, voice, explanations). **Never the plant.** |
| Console (Phase 3) | static files served by `zs-api` at `http://localhost:8090/`. Localhost is a secure browser context, so the microphone works for voice | API only |
| Replay viewer + results (Phase 3) | **Vercel**, static, built from `site/` in the repo, data from committed episode bundles | nothing live; no key, no API |

The API never writes the audit log: human actions go into the inbox, which the core reads. That's the reason for the Phase 1 two-database split.

**API contract** (`docs/API.md`, written in this phase; endpoints **stubbed with tests** in this phase, wired to the UI in Phase 3):
- **Plans:**
  - `GET /api/plants/{plant}/map`: the plant graph for the plant view (nodes, edges, tags, energy sources);
  - `POST /api/plans/import` (csv | text | image) → draft;
  - `GET /api/plans/drafts/{id}`: draft, merged plan, plan-check findings including **open paths as node lists**, so the view can draw them red;
  - `PUT /api/plans/drafts/{id}`: edits from the table, then re-check;
  - `POST /api/plans/drafts/{id}/confirm` → plan hash.
- **Sessions:**
  - `GET /api/sessions/{id}`: status, steps, verdict, stamped versions;
  - `GET /api/sessions/{id}/stream`: SSE of evaluations, findings and verdict changes, tailed from the audit log and `signals.jsonl`;
  - `POST /api/sessions/{id}/steps/{k}/done|verify|reopen` → inbox.
  - `POST /api/sessions/{id}/sign` → inbox. A deliberate on-screen action with name and role; **no voice route reaches this endpoint**.
- **Explain:** `POST /api/sessions/{id}/explain {question}` → Muse Spark answer built **only** from that session's logged findings and windows. The response cites finding ids. It can't change anything.
- **Voice:** `POST /api/voice/command {audio}` → transcript → fixed intent (`step_done k` | `status` | `why` | `repeat` | `unknown`) → **read-back text**.
  - It does **not** act. The console speaks the read-back and calls `/steps/{k}/done` only after the person confirms.
  - Transcription uses the P2-5 result: Muse Voice Transcribe, or the browser's speech recognition as a labelled fallback.

**Episode bundle schema** (`docs/BUNDLE.md`, plus `eval/tools/export_bundle.py` built in this phase): plan and plant map, steps with marks, evaluations with windows, findings, verdict timeline, downsampled signals, camera readings (with frame hashes, not frames), truth for that episode (eval only, clearly marked), and scenario/seed. The Vercel viewer reads only this. Tests: export → load → schema validates; no key-like strings in the output.

**Tests in this phase:**
- `tests/test_api_contract.py`: each stubbed endpoint returns its schema.
- `/sign` is unreachable from the voice route.
- The API can't write `audit.sqlite`, because the volume is mounted read-only.
- `tests/net/` for `zs-api-net`: only the proxy is reachable.

### P2-10 Tag-plate confirmation (stretch; cut before everything else)
A photo of an equipment tag plate → `spark_json {tag}` → must equal `work_equipment`, otherwise FAIL as PLAN-MAPPING at the field step. Demoed with photos of printed plates, labelled as such. Endpoint: `POST /api/sessions/{id}/tagplate`. Only if every other item is done before 18:00.

## Schedule (parallel worktrees: items marked ∥ can run in separate agents)
| When | Items |
|---|---|
| 08:30–09:00 | P2-0 docs |
| 09:00–10:00 | P2-1 proxy + client (everything with a model depends on it) |
| 10:00–13:30 | ∥ P2-2 plan checks + maps · ∥ P2-3 importer · ∥ P2-6 P2 spec + model + server |
| 13:30–16:00 | P2-4 camera (needs the lab) · P2-5 voice (needs your 20 recordings; record them this morning) |
| 16:00–18:00 | P2-6 P2 live smoke + C12 · P2-7a sequence · ∥ P2-9 contracts + API stubs + bundle export · **18:00 P2 go/no-go** |
| 18:00–20:30 | P2-7b/c if time · fixes · full offline test run · P1 + P2 smoke on the final code · P2-10 only if everything else is done |
| 20:30–22:00 | Freeze, seal, launch |

## Gate (outputs into `docs/specs/PHASE_2_GATE.md`)
1. `pytest -q` is green offline: client, plan rules, importer gate, camera, process rules, OPC UA adapter, P2 model (C12 analytic).
2. `pytest -m net` in ZeroState covers: PLC:502 ok, proxy only to api.meta.ai, frames ok, P2 OPC UA ok (if built); everything else blocked, including host.docker.internal, other DMZ hosts and the internet.
3. The plan benchmark has run, and P1's real plan is BLOCKED by PLAN-SOFTWARE/TYPE.
4. Importer accuracy reported for all three routes, with 0 invented points.
5. Camera accuracy reported (C7), plus measured camera lag.
6. Voice result recorded (pass, or fallback decided).
7. P2: smoke passes and C12 passes, **or** the cut is recorded with a reason.
8. `bench-freeze` tag, `sealed_hash.txt` committed before the first scoring episode, and the benchmark running with ≥ 1 valid scoring episode logged before 22:30.
8b. `docs/API.md` and `docs/BUNDLE.md` committed; API stubs pass their contract tests; `zs-api` can reach only the proxy; one smoke episode exported to a bundle that validates.
9. `/ponytail-review branch` findings fixed.

## Stop and report (don't work around)
- The Unity scene won't render in headless Chromium, or no view shows any valve display.
- The Meta API refuses calls through the proxy, or the budget guard trips during development.
- Any model route invents an isolation point that the author didn't write.
- P2's analytic check fails by more than 2 %.
- OPC UA read-only enforcement can't be shown (the `zerostate` user can write).
- The benchmark can't start by 22:30 on the frozen tag.
