# Phase 1 — One live GRFICS episode, end to end (spec, rev 3)

Goal: build a patched GRFICS plant with transmitter noise, valve-position feedback with faults, a passing-valve leak, a time scale and a seeded noise generator. An operator container performs a real isolation through the PLC's manual mode. ZeroState watches over Modbus, runs live checks as pure functions selected by the plan's steps, writes a hash-chained audit log, and returns a verdict that replays identically from the log. A host-side runner drives one episode per scenario and checks the router and IDS before and after.

Not in Phase 1: plan checks, process checks, models, camera, importer, UI, gas line (P2), sealing, benchmark, claims tooling.

## Rev 3 amendments (implementation plan approved Nov 1; these override the text below where they differ)
1. **No seeded noise** (change C and its test removed). Seeds fix fault type, severity and onset only.
2. **`zs session stop <id>`** ends an eval episode: logs `session_stopped` (unsigned, verdict unchanged).
3. **S1 expected: BLOCKED or ESCALATED** (late onset lets ALIVE pass; noise loss gives UNKNOWN). The smoke table records the first rule that fired.
4. **Vent:** plan field `vent_target_kpa_abs: 102`, met by the operator on a rolling mean of 8 polls; `p_depressurised_kpa_abs: 105` stays LIVE-HOLD's acceptance limit.
5. **Spike / rate tests only on pressure and level** (`max_rate_kpa_per_process_s`, `max_rate_level_pct_per_process_s`); flows, valves, analyzer get gross range + freshness only. Level dropout to 0 is a known limit.
6. **Step order:** step k+1 can be marked only after step k is evaluated; the runner polls `zs status --json`. Step 8 evaluates automatically after step 7.
7. **Monitor settle:** the continuous monitor includes a point only once its `settle_process_s` has passed since its step mark. Monitor QUALITY covers all witnesses.
8. **Data mapping:** `Witness.point` ties feedback/command/flow witnesses to an isolation point; `Step.target` is a point id or a tag (`manual_mode`).
9. **Step 1** also runs VALVE in command-only form (`manual_mode` = 1).
10. **`gate.py` (pure verdict policy + stamping) is split from `session.py`**; C10's test file is `tests/test_gate.py`, lifecycle tests in `tests/test_session.py`. Every verdict carries package version, rule ids + versions, threshold versions, plan hash and assumptions used.
11. **`zs session start` needs `--plan-hash`** and refuses on mismatch (minimal "unconfirmed plan → refuse to start").
12. **CLI additions:** `zs status --json`, `zs audit export <session>`.
13. **Operator** gets `--process-time-scale` on every `wait-*`; needs NET_ADMIN for its route (eval tooling; router still limits it to PLC:502).
14. **Marker `live`** for `tests/live/` (`addopts = -m "not net and not live"`). P1-1's leak case runs after P1-3 (needs the operator to close f1). The "≥ 20 distinct raws" check applies to tags above flow cutoff; flows at 0 are checked as exactly 0.
15. **`tests/test_readonly.py`:** the `execute` / `send` ban is scoped to `adapters/` (SQLite uses `execute`; pymodbus is importable only under `adapters/`). `write_*` stays banned everywhere.
16. **Replay** re-runs logged windows with the current rules/thresholds; each evaluation also logs the thresholds it used. One global audit chain.
17. **After any Docker restart:** `docker compose … up -d`, then `apply_router_rules.ps1` (Docker restarts wipe the router rules).
Branch: `p1-work`. Tag: `phase-1`. Due: Sun Nov 1 night.
Order: P1-0 → P1-1 → P1-2 (the time scale decides every process-time number) → the rest in order.

## Facts from GRFICS source (commit `8d611b773fa74e3a82ff149c447cff8380eaa99a`)
- **Main loop.** The simulator ticks every 100 ms of wall time. `dt` is in **hours** and is multiplied by `time_scale`. `time_scale` is hard-coded to 1.0 in `TE::TE()`, with no input that sets it. `sampling_delay` is divided by `time_scale`.
- **Writes.** A write to the socket (`{"request":"write","data":{"inputs":{…}}}`) replaces the global `inputs`. `TE::update` changes a fault member only when its key is present, so fault settings **persist** across later writes from the remote I/O. Valve setpoints are applied on the tick of the write that carries them.
- **Sensor faults** (`apply_sensor_fault`):
  - frozen holds the last value;
  - drift adds `severity·dt`, so severity is in **units per process-hour**;
  - noise is uniform ±severity;
  - dropout reads exactly 0 for part of a 10 s wall-clock cycle;
  - none returns the true value.
  - **Healthy sensors have no noise.** Noise uses `rand()` seeded with `time(NULL)`.
- **Flows.** `F1 = 6.4046·s·pos` and `F2 = 0.4246·s·pos`. Purge is `0.352·s·pos·√(P−100)` and product is `0.0417·s·pos·√(P−100)` when P ≥ 100, otherwise both are 0. Product flow is forced to 0 when the product valve position ≤ 0 or the level ≤ 0. Positions are clamped to 0–100 and pressure to 0–3200.
- **Vessel.** VT = 122 m³, VLmax = 30 m³, T = 373 K. At about 44 % level, the vapour volume is about 109 m³, so **1 kmol of vapour ≈ 28.5 kPa**.
- **Remote I/O** (`feedN.py`, `purge.py`, `product.py`). IR1 is `state.<v>_valve_pos`, the **true** position. IR2 is `measured.<v>_flow`. Each loop writes the HR1 setpoint to the simulator. The tank device serves measured pressure and level.
- **PLC program `326339.st`.** `IF manual_mode THEN <v>_valve_sp := <v>_manual_sp`. The default manual setpoints are f1/f2 = 0 and **purge/product = 65535 (100 %)**. Turning manual on without first writing the setpoints closes the feeds and fully opens purge and product. HR100–103 are PLC outputs, rewritten every scan.
- **Steady state.** f2 sits at 0 % in normal running, so closing it is trivially satisfied. Keep the step anyway, because it's part of a real isolation.
- **Web API.** `index.php` holds a *newly activated* fault for **3 s** before forwarding it, and it interacts with the noise-floor scheduler. Episode fault injection must bypass it.
- **The patch needs no Git LFS.** The web and Unity files stay in the pulled image. Only the C++ binary and the `remote_io/modbus/*.py` files are replaced.

## Physics-derived numbers (from the constants above; confirm in P1-9)
- **Vent time.** With feeds and product closed and purge at 100 %: dP/dt ≈ −1003·√(P−100) kPa per process-hour. From 2700 kPa it reaches **105 kPa in ≈ 5.8 process-min** and 100 kPa in ≈ 6.1 process-min. At ×10 that's about 35 s of wall time.
- **Initial vent rate.** About **14 kPa per process-second** at 2700 kPa.
- **Hold sensitivity.** A passing f1 leak of 1 % adds ≈ 6.4 kmol/h, which is ≈ **+30 kPa over a 600 process-s hold**. Even 0.1 % gives ≈ +3 kPa.
- **Flow cutoff.** The f1 low-flow cutoff (1 % of span = 10 kmol/h) hides leaks below ≈ 1.6 %. Those are caught only by the hold test. This is a real-world property; report it, don't tune it away.

## Items (one commit each, or smaller; `pytest` green before every commit)

### P1-0 Doc alignment (first commit on `p1-work`)
- **PROJECT decision 2 and EVAL.** The hold is `hold_process_s: 600`, the real 10-minute practice value (PetroSA). Only the clock is compressed.
- **ARCHITECTURE §1.1.**
  - Freshness gains a path-level (host) rule.
  - The placeholder rule stays single-value (reason in P1-4).
  - Plans carry explicit steps that name their checks (P1-5).
  - The verdict policy has a pending state and an UNKNOWN grace period (P1-5).
- **ARCHITECTURE stack.** The QARTOD gross-range, spike and rate-of-change tests are implemented in our own code (a few lines each, cited to the QARTOD manual). The `ioos_qc` dependency is dropped (it pulls in pandas and numpy for three formulas).
- **STRUCTURE.** Add:
  - `src/zerostate/cli.py`;
  - `src/zerostate/thresholds/default.yaml`;
  - `plants/p1_grfics/thresholds.yaml`;
  - `plants/p1_grfics/sim_socket.py`, `faults.py`, `truth.py`;
  - `tests/live/`;
  - `eval/tools/timescale_test.py`;
  - the patch folder files.
  Rule: plant-specific thresholds live with the plant, are copied into `/app/config/<plant>/` like the map, and are never in `src/`.

### P1-1 GRFICS patch (`plants/p1_grfics/patch/`, GPL-3.0)
**Setup.**
- Clone GRFICSv3 at the commit above into `D:\grfics\vendor\grficsv3`. It lives outside our repo and needs no LFS.
- Read the pulled image's label `org.opencontainers.image.revision`.
- If it isn't this commit, or reads `unknown`, compare these against the clone: `/app/modbus/*.py`, `/var/www/html/data/index.php` and the JSON keys returned by `GET /data/index.php`, all from the running container.
  - If they all match, proceed and note it in the patch README.
  - If they don't, stop and report.

**Files.** `TE_process.patch`, `remote_io.patch`, `Dockerfile.derived`, `build.ps1`, `LICENSE` (the GPL-3.0 text), and a `README.md` that lists every change below and the image-match result.

**Behaviour changes (exactly these, nothing else):**
- **A. Version marker.** `state.zs_patch_version = "p1-1"`. Truth side only; never served by the Modbus devices.
- **B. Time scale.** `time_scale` comes from env `ZS_TIME_SCALE` (default 1.0), read in the constructor before `sampling_delay` is computed. Print it at startup.
- ~~**C. Seeded noise.**~~ Removed in rev 3: the simulator draws noise per wall-clock tick, so a seed can't make an episode reproducible. Reproducibility = replay from the audit log (C11).
- **D. Transmitter noise.** Env `ZS_NOISE` (default 1).
  - Add uniform noise of ±0.1 % of span to measured pressure (3200), level (100), f1 flow (1000), f2 flow (500), purge flow (2000), product flow (500) and analyzer A/B/C (1).
  - Apply it in healthy mode, on top of **drift**, and in the non-dropped phase of **dropout**. Never in **frozen**, nor in the existing **noise** fault mode.
  - Low-flow cutoff: a measured flow below 1 % of span reads 0.
  - Clamp measured values to their physical range: flows ≥ 0, analyzer 0–1, pressure 0–3200.
- **E. Valve position feedback.** New `measured.<v>_valve_pos` for f1, f2, purge and product: the true position ± 0.1 % noise, clamped to 0–100.
  - New inputs `<v>_pos_fault_mode` and `<v>_pos_fault_severity`. Modes:
    - 0: none;
    - 1: frozen, holds the last value;
    - 2: offset, +severity %;
    - 3: reads a fixed value, severity %. Severity 0 is the Giant 2004 case (reads closed while open); severity 100 is the Milford Haven case (reads open while closed).
  - Truth: `state.<v>_pos_fault_mode`, `state.<v>_pos_fault_severity`.
- **F. Passing-valve leak.** New input `<v>_leak_pct` (0–100, default 0).
  - Flow uses `max(true_pos, leak_pct)` as the effective opening, including in the product "position ≤ 0 → flow 0" line.
  - True position and feedback are **unchanged**.
  - Truth: `state.<v>_leak_pct`.
- **G. Remote I/O.** IR1 on the four valve devices reads `measured.<v>_valve_pos` instead of `state.<v>_valve_pos`.
- **Unchanged:** e-stop, existing faults, the noise-floor scheduler, web files, the PLC.

**`Dockerfile.derived`.**
- Stage 1: the same base digest as GRFICS's build stage (`python:3.11-slim@sha256:7a3ed1226224bcc1fe5443262363d42f48cf832a540c1836ba8ccbeaadf8637c`) plus `build-essential libjsoncpp-dev liblapacke-dev`. Copy the patched `simulation/simulation`, then `make`.
- Stage 2: `FROM fortiphyd/grfics-simulation@<digest>` (from `docker image inspect` of the pulled image). Copy the binary to `/app/simulation/simulation` and the patched scripts to `/app/modbus/`.
- Tag the result `zerostate/grfics-simulation:p1-1`.

**Compose.**
- Add a `simulation:` override to `deploy/docker-compose.zerostate.yml`: `image: zerostate/grfics-simulation:p1-1`, `build: !reset null`, `pull_policy: never`, environment `ZS_TIME_SCALE`, `ZS_NOISE`, `ZS_NOISE_SEED`, with values from host env variables that have defaults.
- Fortiphyd's file stays untouched.
- `docker compose config` must show no build context for `simulation`.

**Helpers (host side, under `plants/p1_grfics/`, never imported by `src/`).**
- `sim_socket.py`: a 20-line script piped into the simulation container with `docker exec -i simulation python3 -`. It reads or writes the simulator socket on 127.0.0.1:55555.
- `faults.py`: builds the fault dicts and calls `sim_socket.py`.
- `truth.py`: reads truth via `GET http://localhost/data/index.php`. GET has no delay.

**Tests (`tests/live/test_patch.py`, run from the host).** Modbus is read through `docker exec -u zs zerostate python scripts/modbus_scan.py …`, because the host can't reach the macvlan network. Truth is read through `truth.py`.
- `zs_patch_version == "p1-1"`.
- Over 30 s, every noise-carrying tag shows ≥ 20 distinct raw values on Modbus.
- Feedback on Modbus is within 0.3 % of truth.
- f1 commanded to 0 with `f1_leak_pct=2` → measured f1 flow ≈ 12.8 kmol/h (±3) while the feedback reads ≈ 0.
- `f1_pos_fault_mode=3`, severity 0, with f1 open → the Modbus feedback reads ≈ 0 while truth is > 50.
- **Fault persistence:** a fault set, then 5 s of normal remote-I/O writes → the fault is still active.
- All faults are cleared at the end.

### P1-2 Time-scale stability test (`eval/tools/timescale_test.py`, host)
- **Runs.** Two runs with the PLC in AUTO, 15 min of wall time each, after a 120 s warm-up: `ZS_TIME_SCALE=1` and `=10`, each by recreating the simulation container. Log truth at 2 Hz.
- **A scale passes when:**
  - pressure and level means are within ±5 % of nominal (2700 kPa, 44 %);
  - the standard deviation over the last 5 min is ≤ 2 × that scale's first 5 min;
  - the ×10 standard deviation is ≤ 3 × the ×1 standard deviation.
- **Decision.**
  - If ×10 passes, use ×10. Otherwise try ×5.
  - If ×5 also fails, run in real time with 3 episodes per scenario and 10 clean. An episode then takes ≈ 20 min of wall time, so plan the smoke run accordingly.
  - Record the result in DECISIONS.md and in `process_time_scale` in the map. Every process-second number below converts through it.
- **Risk:** the PLC loops are tuned for real time.

### P1-3 Operator container (`plants/p1_grfics/operator.py`, `Dockerfile.operator`)
- **Network.** Service `zs-operator` on `c-dmz-net` at 192.168.90.70. `apply_router_rules.ps1` adds ACCEPT .70 → 192.168.95.2:502 and DROP everything else from .70, both above the allow-all.
- **CLI** (`docker exec zs-operator python operator.py …`):
  - `status`: prints measured pressure, valve feedbacks, commands, manual_mode and manual setpoints, all read over Modbus as a human would see them;
  - `manual on|off`;
  - `set <f1|f2|purge|product> <pct>`;
  - `wait-pressure-below <kPa> --timeout-process-s N`;
  - `wait-valve <v> <pct> --tol 1 --timeout-process-s 120`.
- **`manual on` is bumpless.**
  1. Read the current commands (HR100–103).
  2. Write them into the manual setpoints (HR10–13).
  3. Read the setpoints back.
  4. Only then set coil 0.
  Any readback mismatch aborts.
- **`manual off`:** clear coil 0, then restore the PLC's default manual setpoints (0, 0, 65535, 65535), so every episode starts from the same PLC state.
- **Write scope.** Every write is followed by a readback. The operator only writes coil 0 and HR10–13. Writing HR10 while manual is off is how S6 is produced: it's the "set from the screen while the controller is in AUTO" case.
- **Live map confirmation.** Set `confirmed: true` for coil 0 and HR10–13 in the map in this commit.
- **Test.** `tests/test_operator.py`, against an in-process Modbus server. It asserts the write order (setpoints before the coil), that a readback mismatch aborts, and that `manual off` restores the defaults.
- The operator is eval tooling. It lives under `plants/`, and `src/zerostate` never imports it.

### P1-4 Freshness: path rule and noise retune
- **Path rule.** If every noise-carrying tag reached through the same `host` is static past its window, every tag from that host becomes STALE. This is fail-safe.
- **Map retune (after P1-1/P1-2).**
  - Valve feedback: `constant_ok_raw: [0, 65535]`.
  - Flows: `[0]`.
  - Pressure, level, analyzer: `[]`.
  - Commands, setpoints, manual_mode: `any`.
  - Noisy tags: `max_static_wall_s: 5`.
- **Placeholders.** Keep the single-value `203` rule, and document why. After the patch, a collision needs a valve resting at exactly 0.31 % open, and the error direction is UNKNOWN, which is safe.
- **Tests (fake clock):**
  - a host-wide freeze makes everything STALE, including valves at their end stops;
  - one noisy group static while another changes makes only that group STALE;
  - after a change, tags recover to GOOD.

### P1-5 Plan steps, session engine, verdict policy (`src/zerostate/session.py`, `src/zerostate/cli.py`)
**Model change (`models/envelope.py`, frozen plan).** Add `steps: tuple[Step, ...]` to `IsolationPlan`:
- `Step{k, kind: mode|isolate|vent_open|vent_close|hold|final, target: tag|None, required_state: float|None, checks: tuple[rule_id, ...], settle_process_s, timeout_process_s}`.
- Plan-level fields:
  - `p_depressurised_kpa_abs`: one number, used by the operator's vent target **and** by LIVE-HOLD;
  - `hold_test{hold_process_s, window_process_s, max_rise_kpa, upstream_min}`.
- This keeps the step-to-checks mapping in **data**, not code, which is the plant-agnostic rule. Update `test_models.py`, because the plan hash changes.

**P1 plan (`plants/p1_grfics/envelope.yaml`, full).** Reactor vapour-side work. Declared assumption: "positive isolation upstream assumed". `p_depressurised_kpa_abs: 105`. `hold_test: {hold_process_s: 600, window_process_s: 60, max_rise_kpa: 5}` (provisional).

| k | kind | target | required | checks run at evaluation |
|---|---|---|---|---|
| 1 | mode | manual_mode | 1 | QUALITY |
| 2 | isolate | f1 | 0 | QUALITY, VALVE |
| 3 | isolate | f2 | 0 | QUALITY, VALVE |
| 4 | isolate | product | 0 | QUALITY, VALVE |
| 5 | vent_open | purge | 100 | QUALITY, ALIVE, RELATION, VALVE (open) |
| 6 | vent_close | purge | 0 | QUALITY, VALVE |
| 7 | hold | — | — | QUALITY, HOLD, VALVE (all closed points, whole window) |
| 8 | final | — | — | all previous steps PASS |

Witnesses: pressure, all valve feedbacks, commands and flows. Relation: `valve_sqrt_law` for purge (k = 0.352, p_floor = 100).

**Storage.** A `zs-data` volume at `/data`, writable by `zs`:
- `/data/audit.sqlite`: the core is the only writer;
- `/data/inbox.sqlite`: human and operator actions (step marks, signatures), which the core reads;
- `/data/runs/<session>/signals.jsonl`: every poll, raw and scaled, with quality.

The split lets the Phase 3 operator page (a separate container with a published port) write human actions without ever writing the audit log.

**CLI.** A `zs` console script in `pyproject.toml`, run via `docker exec -u zs zerostate zs …`:
- `zs session start --plan <path> --session <id>`: a long-running monitor that polls at 4 Hz;
- `zs status <session>`: shows `warming_in` → `ready` → per-step status → verdict;
- `zs step done <session> <k> --by <name>`;
- `zs sign <session> --by <name> --role receiver [--note …]`.

**Session lifecycle and verdict policy.**
- **Warm-in.** After start, the session is `warming_in` until every witness has been seen changing and is GOOD, with a timeout of 30 s wall (→ ESCALATED, reason "instruments not verified live"). Step marks are refused until `ready`.
- **Pending.** A step mark starts that step's evaluation. The step is `pending` until its windows are complete (settle elapsed, vent check elapsed, hold elapsed). Pending is not a verdict.
- **Evaluation.** When the windows are complete, run the step's checks once:
  - any FAIL → `BLOCKED` (stop evaluating later steps);
  - otherwise any UNKNOWN → `ESCALATED`;
  - otherwise the step PASSes.
  - After step 8 → `NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF`.
- **Continuous monitoring** (OSHA 1910.147(d)(5)(ii)). From step 2 on, every 2 s, re-check QUALITY and VALVE for all points already isolated:
  - a FAIL → `BLOCKED` immediately;
  - an UNKNOWN that persists > `monitor_unknown_grace_wall_s: 10` → `ESCALATED`. The grace applies to UNKNOWN only, never to FAIL.
- **Monotonic.** The verdict only gets worse automatically. Only a human signature closes the session. `zs sign` records the signature whatever the verdict, with the verdict at signing time in the audit log.

### P1-6 Live checks (`src/zerostate/checks/live/`)
Rules for every check:
- **Pure function:** `check(plan, step, window, params) -> Finding`. The `window` holds the recorded samples (tag → list of `(recv_ts, value, raw, quality)`) plus `process_time_scale`.
- No input/output, no clock, no randomness.
- Exports `RULE_ID` and `RULE_VERSION`.
- Thresholds are merged from `src/zerostate/thresholds/default.yaml` and `/app/config/<plant>/thresholds.yaml`. Every threshold name ends in `_process_s`, `_wall_s` or a unit (`_kpa`, `_pct`, `_per_process_s`).

**LIVE-QUALITY** (`quality.py`):
- **UNKNOWN** if any witness of this step is STALE, UNKNOWN or BAD in the window.
- **FAIL** if a value is physically impossible: pressure < 50 kPa abs or > 3200; level outside 0–100; a flow outside 0–span. The pressure floor is what catches a dropout to 0 near the end of the vent, where the jump is too small for the rate test.
- **FAIL** if the rate of change exceeds `max_rate_kpa_per_process_s: 50`. The largest legitimate rate is ≈ 14 at vent start. This catches dropout jumps at high pressure.
- Spike test per QARTOD, with its limit in thresholds.
- Confirm the minimum S0 hold pressure in P1-9. It should stay far above 50.

**LIVE-ALIVE** (`alive.py`), on the vent_open step:
- Needs purge feedback ≥ 50 % and purge flow above cutoff.
- Then pressure must fall by ≥ 10 % of its starting gauge value (P − 100) within `vent_check_process_s: 120`. The expected fall is ≈ 55 %.
- **FAIL** if it doesn't (S1). **UNKNOWN** if the preconditions never held.

**LIVE-RELATION** (`relation.py`), on the vent_open step:
- While purge feedback ≥ 5 % and measured P ≥ 150: `P_est = 100 + (F_purge / (0.352·x))²`.
- **FAIL** if the relative residual > `tol_rel: 0.10` for ≥ `n_consec: 4` samples.
- A one-sided CUSUM on the residual (k and h provisional) → **FAIL** with "slow drift".
- The message names both possibilities: "instrument wrong, or valve fouled / feedback wrong".

**LIVE-VALVE** (`valve.py`). For each targeted point, after `settle_process_s: 60`. On the hold step, applied to all isolated points over the whole window.

| Condition | Result | Catches |
|---|---|---|
| command ≠ required (±1 %) | FAIL "commanded state wrong" | S5, S6 |
| feedback ≠ required (±1 %) | FAIL "valve did not reach position" | stuck |
| required closed, feedback ≤ 1 %, flow > cutoff | FAIL "flow through a valve reading closed: passing valve or false feedback" | S8, S4 ≥ 1.6 % |

For purge and product, the flow rule applies only while P > `p_depressurised_kpa_abs`.

**LIVE-HOLD** (`hold.py`), on the hold step:
- Compare the mean of the first `window_process_s` with the mean of the last.
- **FAIL** if the rise > `max_rise_kpa`, or if the final mean > `p_depressurised_kpa_abs`.
- **UNKNOWN** if LIVE-QUALITY isn't PASS for the whole hold.
- **Never compare single samples.**
- Catches S4 at any leak size down to ≈ 0.2 % (see the physics numbers).

**Tests.** `tests/checks/test_<rule>.py`, each with at least one PASS and one FAIL case from synthetic windows. Add UNKNOWN cases for QUALITY, ALIVE and HOLD. Add a test that every rule converts thresholds via `process_time_scale` (the same synthetic process trajectory at scale 1 and 10 gives the same result).

### P1-7 Audit log and replay (`src/zerostate/audit/`)
- **Table.** `events(id INTEGER PRIMARY KEY, ts, session, kind, payload_json, prev_hash, hash)`. Triggers `BEFORE UPDATE` and `BEFORE DELETE` → `RAISE(ABORT)`. `hash = sha256(prev_hash ‖ canonical_json(row without hash))`.
- **Event kinds:**
  - `session_start`: plan hash, versions of package, rules and thresholds, `process_time_scale`;
  - `ready`;
  - `step_done`;
  - `evaluation`: the exact window used, inline, plus step and rule list;
  - `finding`;
  - `verdict`;
  - `signature`.
- `zs audit verify <session>` recomputes the chain.
- `zs replay <session>` re-runs every logged evaluation from its logged window. It must reproduce identical findings and verdicts.
- **Tests.**
  - `test_audit_chain.py`: update and delete are rejected; a tampered row is detected.
  - `test_replay.py`: a recorded synthetic session replays identically; changing one threshold makes replay report a mismatch.

### P1-8 Episode runner (`eval/runner.py`, host) and Phase 1 scenarios
**Usage.** `python eval/runner.py --plant p1 --scenario S0 --seed 7`. Seeds 0–999 are **tuning seeds**; the runner refuses any other seed in Phase 1. The seed sets the fault type parameters, severity and onset. Episodes are pre-registered by seed and replayable from logs, never "regenerable".

**Preflight (abort if any check fails):**
- router rules for .60 and .70 present and above the allow-all;
- Suricata rules loaded;
- noise-floor `enabled=false`;
- record the IDS log size and inode as the offset;
- `operator.py manual off`, and confirm the defaults.

**Episode:**
1. Recreate the simulation container with the decided `ZS_TIME_SCALE`.
2. Check `zs_patch_version == "p1-1"`, and that the time scale equals the map's `process_time_scale`.
3. Warm up for 120 s wall, and until truth pressure stays within 2 % of 2700 for 30 s. This also covers GRFICS's undefined initial purge position.
4. `zs session start` (detached). Wait for `ready`.
5. For each plan step, perform the operator action, then `zs step done`:
   - steps 1–4, 6: `manual on` / `set <v> 0`;
   - step 5: `set purge 100`, then `wait-pressure-below 105 --timeout-process-s 900`. If it times out, mark the step done anyway: the hurried human, reading a gauge that never got there.
   - step 7: wait out the hold.
   - Inject the scenario's fault at its seeded onset, via `faults.py`, which uses the socket and not the web API.
6. Log truth at 4 Hz into `truth.jsonl` for the whole episode.
7. Stop at a terminal verdict (BLOCKED or ESCALATED), or at the end of the hold + 30 s process time.

**Postflight (episode invalid if any check fails):**
- the router rules are still present;
- IDS alerts after the offset: 9100001 == 0 and 9100002 > 0 (if the log rotated, i.e. its size is below the offset, count the whole new file plus the rotated one);
- S12: `supervisorctl start modbus`;
- `operator.py manual off`.

**Output** `runs/<episode>/`:
- `meta.json`: scenario, seed, params, versions, image digests, time scale;
- `truth.jsonl`, `audit_export.json`, `verdict.json`, `ids.json`.

**Scenario YAMLs (`eval/scenarios/`):**

| ID | Fault | Onset | Expected |
|---|---|---|---|
| S0 | none | — | NO_DISCREPANCY |
| S1 | pressure frozen | during vent (10–60 process-s after step 5) | BLOCKED (ALIVE or QUALITY) |
| S1b | pressure frozen **and** `f1_leak_pct` 1–3 | at step 6 (gauge freezes at ~105 while the true pressure climbs) | ESCALATED or BLOCKED (noise loss → QUALITY); labelled "depends on our noise model" |
| S2 | pressure dropout, duty 0.3–0.7 | random step from 5 to 7 | BLOCKED (QUALITY) |
| S3 | pressure drift −(2000–6000) kPa per process-hour | during vent | BLOCKED (RELATION) |
| S4 | `f1_leak_pct` 0.5–5 | before step 2 | BLOCKED (VALVE if ≥ 1.6 %, else HOLD) |
| S5 | operator sets f2 when the plan says f1 | at step 2 | BLOCKED (VALVE: command) |
| S6 | manual mode not switched on; operator writes HR10 = 0 for f1 | at step 2 | BLOCKED (VALVE: command) |
| S8 | `f1_stuck=1` **and** `f1_pos_fault_mode=3`, severity 0 | before step 2 (valve stays open, reads closed) | BLOCKED (VALVE: flow through a valve reading closed) |
| S12 | `supervisorctl stop modbus` in the simulation container | during the hold | ESCALATED (path rule → QUALITY) |

### P1-9 Smoke run (tuning seeds only)
- Run each scenario once, and S0 three times.
- **Expectations:** as in the table above. Also record the vent time to 105 kPa and the minimum hold pressure in S0, and compare them with the physics-derived numbers.
- **If S0 blocks:** fix the threshold on tuning seeds only, bump the thresholds-file version and write a one-line reason in DECISIONS.md.
- **If a fault scenario passes:** that's a dangerous miss. Investigate. **Never** loosen a rule that a fault scenario depends on just to make S0 pass.
- **Smoke table columns:** scenario, seed, expected verdict, actual verdict, first FAIL rule, time to block (process-s), vent time, minimum hold pressure.

## Gate (paste outputs into `docs/specs/PHASE_1_GATE.md`)
1. The patched image is running with `zs_patch_version = p1-1`. `docker compose config` shows no simulation build. The image-match result is recorded. `tests/live/test_patch.py` passes.
2. The time-scale decision is recorded with its stability numbers.
3. `pytest -q` is green offline, including the new tests: operator, the freshness path rule, the 5 live rules plus the time-scale invariance test, models (steps), session (warm-in, pending, grace, monotonic verdict), audit chain, replay.
4. `docker exec -u zs zerostate pytest -m net -q` still passes 15/15. zs-operator cannot reach 192.168.95.45:80 or :55555.
5. Every row of the smoke table matches its expected verdict, and every episode has a valid postflight.
6. `zs replay` reproduces every smoke episode's verdict, and `zs audit verify` passes for all of them.
7. `check_ids.ps1 -RequireOperator` per episode: 9100001 = 0 and 9100002 > 0.
8. `/ponytail-review branch` findings are fixed.

Claims after Phase 1: C1, C4, C9 and C11 become "built, evidence pending". They become PASSING only through the claims audit in Phase 3. Nothing is marked PASSING by hand.

## Stop and report (don't work around)
- The pulled image doesn't match the clone (P1-1 setup).
- The derived image won't build, or the binary crashes with the pulled image's libraries.
- Faults don't persist, or seeding isn't reproducible.
- Both ×10 and ×5 are unstable.
- Bumpless manual transfer still moves a valve.
- The measured vent time or hold sensitivity is off from the physics-derived numbers by more than 2×. That would mean a wrong assumption somewhere.
- S0 can't pass without loosening a rule that a fault scenario depends on.
