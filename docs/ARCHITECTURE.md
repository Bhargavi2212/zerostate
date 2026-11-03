# ZeroState — architecture

Status: approved design, revised Oct 31 after independent review. Principle: models read, extract and explain; deterministic code decides; a human signs. ZeroState has no write code path to any plant.

```
 Plant network(s)                               ZeroState container (DMZ)
 ┌──────────────────────────┐  Modbus FC1-4   ┌──────────────────────────────────────┐
 │ P1: OpenPLC 192.168.95.2 │◀── via router ──│ 1 Adapters → Signal{tag,val,quality,  │
 │     remote I/O .10–.15   │                 │   source_ts?, recv_ts}                │
 │ P2: OPC UA server        │◀── read only ───│ 2 Envelope + plant graph              │
 └──────────────────────────┘                 │ 3 Plan checks  4 Live checks          │
 Frame service (separate container) ─frames──▶│ 5 Process checks  6 Camera channel    │
   (only emits frames; has truth access by    │ 7 Gate → verdict + evidence tree      │
    design on P1 = "idealised camera")        │ 8 Audit log  9 API + operator page    │
                                              └──────────────────────────────────────┘
 eval/ + plants/*/truth.py, operator.py, faults.py: the ONLY code that touches truth or writes
 Operator container (DMZ .70): runs operator.py; router allows it only PLC:502.
 eval runner, faults.py, truth.py run on the host (GRFICS web API via localhost:80; operator via docker exec), never in ZeroState's container.
 zerostate-net (helper, NET_ADMIN) owns the DMZ address .60, route and egress allowlist; ZeroState joins its namespace with no capabilities.
 Egress proxy zs-proxy (172.30.0.2:8888, CONNECT to api.meta.ai:443 only): the only route from ZeroState to the Meta API,
   over the internal network zs-internal; ZeroState itself has no internet.
 Frame service zs-frames (172.30.0.3:8080 on zs-internal; reaches the simulator over a-grfics-admin): serves /frame only.
```

## 1. Adapters (read-only)
- Interface exposes only `read`, `subscribe`, `history`. No write method exists in our code. (The pymodbus library itself can write; read-only at the protocol level is enforced by network policy — §1.3.)
- Modbus: pymodbus, function codes 1–4 only. OPC UA: asyncua, read-only user. PI Web API: stretch.
### 1.1 Data quality — what "good" means
- **Modbus has no source timestamps, and GRFICS serves stale data with successful reads**: before the simulator connects, remote I/O registers hold placeholder values (`modbusdevice.py`); if the simulator link dies, registers keep their last values. So read success ≠ good quality.
- Freshness is inferred from **process noise** (decision 13): measured values carry transmitter noise (~0.1% of span; added by our patch on P1, part of the model on P2), so a healthy reading changes every poll. A signal unchanged beyond `max_static_wall_s` (wall clock) is `STALE`. Signals that are legitimately flat (valves at end stops, flows at low-flow cutoff) are allowed by `constant_ok_raw` and stay GOOD but expose how long they've been static. A source group is dead when every noisy tag in it is static. Which values may legitimately sit still is per tag (`constant_ok_raw`: `any` or a list of raw values, e.g. `[0]` for flows at cutoff). The patch's low-flow cutoff is for realism (real flow transmitters have one); GRFICS already clamps raw values to 0–65535. Placeholder **raw values** recorded by the Phase 0 scan → `UNKNOWN`. A tag not yet seen changing is `UNKNOWN` (a fresh tracker must not trust frozen data). This catches a break anywhere along sim → I/O → PLC → network, because the noise must survive the whole path. Freeze detection therefore depends on our noise model, and results say so.
- **Path rule (built in Phase 1):** groups are per I/O device, but every P1 tag reaches ZeroState through one PLC. If every noise-carrying tag from the same host has stopped changing, every tag from that host is `STALE`. Seen live on Oct 31: during a sim restart the tank went STALE while purge and feed2 (valve closed, flow 0, no noise-carrying tag) stayed GOOD behind the same frozen PLC. Errs safe: if only one device died, the rest are marked STALE too (blocks, never passes). Tested in `test_freshness.py` and part of S12.
- **Placeholder rule (decided Phase 1: stays single-value):** a raw 203 on a valve position means placeholder. After the patch a collision needs a valve resting at exactly 0.31 % open, and the error direction is UNKNOWN (safe). The "whole device at seed values" alternative does not match the Oct 31 scan (flows on the same devices were not seeds).
- **Spike / rate-of-change tests (QARTOD) apply only to continuous state variables: pressure and level.** Valves have no travel time in GRFICS (f1 flow 640 → 0 in one tick) and the analyzer jumps on its sampling delay, so flows, valve positions and analyzer get gross-range + freshness only. Known limit: a level dropout to 0 is in range and not caught (level is not evidence for a vapour-side isolation).
- OPC UA: StatusCode and SourceTimestamp used directly; Bad/Uncertain/old → `UNKNOWN`.
- Any `UNKNOWN`/`STALE` evidence a check depends on → that check returns UNKNOWN → verdict cannot be NO_DISCREPANCY.
### 1.2 P1 register map (from GRFICS source; confirm by live scan in Phase 0, incl. address offset)
Remote I/O (port 502, unit id ignored): Feed1 .10, Feed2 .11, Purge .12, Product .13 → IR1 valve position (0–100%, **true position** — source reads `state.*_valve_pos`), IR2 flow (full scale 1000 / 500 / 2000 / 500); HR1 valve command. Tank .14 → IR1 pressure (0–3200 kPa), IR2 level (0–100%). Analyzer .15 → IR1–3 A/B/C. PLC .2 mirrors them at %IW100–112, commands %QW100–103; manual mode coil %QX0.0, manual setpoints %QW10–13. **No temperature, gas detector or e-stop register exists.**
### 1.3 Firewall (network level + code level)
- Network: the ZeroState container can reach only the PLC's Modbus port (P1), the OPC UA endpoint (P2), the model proxy and the frame service, enforced twice (decision 16): (1) router FORWARD rules allow .60 → PLC:502 and drop everything else from .60; (2) an egress allowlist (OUTPUT policy DROP; IPv4 and IPv6) set by a separate helper container `zerostate-net`, because same-subnet DMZ traffic and traffic to the router itself never pass FORWARD. ZeroState joins the helper's network namespace with `cap_drop: ALL`, so even root inside ZeroState can't change routes or rules. The helper itself has NET_ADMIN: it plays the firewall appliance, like the router, and anyone who can `docker exec` into it (i.e. the host operator) can change the rules. C1 covers the ZeroState container and its code, not the host or the helper. ZeroState joins no bridge network (a bridge reaches Windows-published ports via `host.docker.internal`, including truth :80 and OpenPLC's web UI :8080). Tests from inside the container must fail to connect to: GRFICS truth :80 and :55555 (simulator JSON socket, carries truth and fault flags), remote I/O, PLC web :8080, `host.docker.internal` :80/:8080, other DMZ hosts, the router, and the internet.
- The router cannot filter Modbus by function code (Suricata runs IDS-only), so writes are evidenced, not blocked, at network level: a Suricata rule alerts on any Modbus write from ZeroState's IP (sid 9100001, must stay 0). The same rule for the operator container's IP (sid 9100002) must fire every episode — a positive control proving the rule and the IDS's view of the traffic (decision 15). The episode runner checks the router rules and Suricata rules are present before and after every episode; missing → episode invalid. It counts alerts per episode from the `eve.json` byte offset recorded before the episode (file shrank → rotated → count from 0), so rotation can't hide an alert.
- Internet (Phase 2+): ZeroState never has it. Meta API calls go through the egress proxy (CONNECT `api.meta.ai:443` only; TLS end to end, so the proxy never sees the key) over the internal-only network `zs-internal` (decision 14). Only `llm/client.py` names the Meta host; only `llm/client.py` and `camera/client.py` may open HTTP connections, each with an explicit proxy setting. The API container (`zs-api`, port 8090 bound to 127.0.0.1) has its own helper whose allowlist is the proxy only.
- P2 (OPC UA): read-only is enforced by the server (user `zerostate` may only read; `operator` may write `*.CMD` only) and evidenced by the server's write log: 0 attempts by `zerostate` per episode. The IDS can't parse OPC UA.
- Code: `src/zerostate` imports nothing from `plants/` or `eval/` and contains no truth URLs (AST test).
- The frame service is outside ZeroState. On P1 it necessarily renders truth; that is declared, not hidden.

## 2. Isolation envelope (plant-agnostic data model)
Pydantic schema, YAML, keyed by plant tags; field names follow SAP PM WCM and IBM Maximo HSE.
- `WorkScope{equipment, task, permit_ids}`; `EnergySource{tag, type, max_magnitude}`
Two halves (decision 18): **`IsolationPlan`** (everything below except `SessionState`) is frozen and hashed once a person confirms it; **`SessionState`** holds what changes during the job and references the plan hash.
- `IsolationPoint{tag, device: block_valve|control_valve|blind|spade|spool_removed|breaker, isolation_type: positive|proved|non_proved, normal_state, required_state, apply_seq, remove_seq, lock_id, tag_id}`
- `ProvingPoint{tag, kind: vent|bleed|drain|test_point, proves: [IsolationPoint], discharges_to}`
- `Segment{id, members, bounded_by, vents}`; plant graph in NetworkX.
- `Witness{segment, signal_ref, role, side: work|upstream|between_blocks, redundancy_group, point}` — `point` ties a witness (role feedback / command / flow) to an isolation point, so checks find a point's tags from data.
- `Step{k, kind: mode|isolate|vent_open|vent_close|hold|final, target, required_state, checks, settle_process_s, timeout_process_s}` — the plan's ordered steps, each naming the rule ids it runs; step-to-check mapping is data, not code. Plan fields `vent_target_kpa_abs` (operator goal, rolling mean) and `p_depressurised_kpa_abs` (acceptance limit for LIVE-HOLD).
- `Relation{type, signals, params}` — plant physics as data, e.g. `valve_sqrt_law: F = k·x·sqrt(P − p_floor)` (P1: k_purge 0.352, k_product 0.0417, p_floor 100 kPa).
- `Assumption{text, scope}` — declared out-of-scope facts (e.g. P1 "positive isolation upstream assumed"); printed in every verdict that relies on them.
- `HoldTest{hold_process_s, window_process_s, max_rise_kpa, upstream_min}` — fixed before the run. Process-seconds, converted to wall time with the plant's declared `process_time_scale` (decision 17). The rise is the mean of the last window minus the mean of the first window, never single noisy samples; `max_rise` sits above the noise band of a window mean.
- `SessionState{plan_hash, point_status: {tag → ITG|ETG|ETUG|EUG}, signatures: [Signature], step_log: [step, ts]}`
- `Signature{role: planner|approver|installer|verifier|prover|receiver, person, ts}`
A plan is usable only after human confirmation (hash recorded); any edit to the plan invalidates it. Session changes never touch the plan hash.
- **Plan = plant map + isolation list (Phase 2).** `plants/<p>/plant_map.yaml` (data): nodes `source` (energy type, pressure, `hazardous`), `vessel`/`segment`, `valve` (`device: block_valve|control_valve|check_valve`, `actuation: manual|actuated`, `normal_state`), `vent`/`bleed` (`discharges_to: atmosphere|flare|header:<id>`), `relief`, `heater`, `instrument` (role, `at: <node>`, signal_ref); edges = pipes; `plan_defaults` (hold test, vent targets, step check sets, settle times, camera). `IsolationList` (what a person authors; the importer's output): `work_equipment`, `points[{tag, required_state, seq, isolation_type}]`, `vent`, `proving[{tag, proves}]`, `hold_minutes`. `graph/build.py` merges them deterministically into an `IsolationPlan`. P1's live plan stays hand-written (decision 22). A witness's side is computed from the map and the closed points, not declared per job.
- `IsolationPlan.camera: optional | required`: optional = a camera UNKNOWN (model down, unreadable) is logged and ignored, a camera FAIL blocks the with-camera track; required = a camera UNKNOWN also escalates it. `hold_pressure_kpa_abs` (P2 holds at residual pressure, decision 24). `Signature.role` adds `issuer` (confirms a plan).

## 3. Plan checks (deterministic, graph)
| Rule id | Check | Real case | Test plant |
|---|---|---|---|
| PLAN-PATHS | with isolation points in required state, no path from any source to work segment | missed line (HSG253) | P2, plan set |
| PLAN-LIVESIDE | the work is on a listed isolation device itself, or inside a listed device's boundary (the device relied on is the one being opened) | LyondellBasell 2021 | P2, plan set |
| PLAN-BOXEDIN | closed volume with heat source and no relief path | Williams 2013 | P2 (heater), plan set |
| PLAN-SOFTWARE | isolation by control valve / software deselect only | HSG253 case; 1910.147(b) | P1 (fires by design), plan set |
| PLAN-TYPE | a hazardous source isolated only by non-proved points (proved single block and bleed counts as proved) | HSG253 | P1, P2 |
| PLAN-PROVING | proved isolation has a proving point; bleed not into pressurised header | IChemE LPB 250 | P2 |
| PLAN-MAPPING | every tag exists; witnesses on correct side | Pemex 2024, Formosa 2004 | P1, P2 |
Findings carry the open path as a node list (for drawing). P1 runs live with `--plan-check-override "<text>"`, logged at session start and printed with every verdict; without it a plan BLOCK refuses the session. Plan-check findings are logged as an evaluation and replayed.
Shared-point conflicts across permits: stretch (needs multiple envelopes).

## 4. Live checks (deterministic)
| Rule id | Check | Notes |
|---|---|---|
| LIVE-QUALITY | fresh, not placeholder, gross range; spike + rate only on pressure and level (QARTOD, own code) | §1.1 |
| LIVE-ALIVE | instrument moved consistently with a known disturbance (the depressurisation) before being trusted; vent open with no flow and no fall = blocked vent (FAIL) | "after" check where a post-hold disturbance exists: P2's final vent from the 200 kPa hold (decision 24). On P1 a gauge frozen after the vent at the true value is caught only by noise loss (LIVE-QUALITY) — depends on our noise model, labelled in EVAL. |
| LIVE-RELATION | residual between signal and physics relation / redundant sensor (2-of-3 where available); CUSUM for slow drift (inside this rule) | P1 redundancy = pressure vs purge/product flow laws only while valves open and P > ~150 kPa |
| LIVE-UPSTREAM | upstream pressure present during hold (not a dry test) | P2 only (P1 has no upstream sensor) |
| LIVE-HOLD | mean of first window vs mean of last window: rise ≤ `max_rise_kpa` on every work-side gauge; final mean ≤ `p_depressurised_kpa_abs` (P2: checked at the final vent instead; between-blocks gauges stay ≤ it) | never single samples |
| LIVE-VALVE | command vs position feedback; commanded closed with flow above the low-flow cutoff | needs patch on P1 |
| LIVE-CAMERA | camera reading agrees with data within measured lag window | idealised on P1 |
| LIVE-REPLAY | repeated window / autocorrelation | stretch |
Transients: "unexpected change" alarms suppressed during commanded transients; invariants never suppressed. Generic checks for gas detectors / temperature exist in the design only when a plant has those signals; neither test plant does, so they are not built or claimed.

## 5. Process checks
Fixed step order from the envelope, stop at first failure (PROC-SEQUENCE); installer ≠ verifier ≠ prover (PROC-INDEPENDENCE); temporary de-isolation (ETUG) resets affected segments (PROC-RESET). Re-prove interval: stretch.

## 6. Camera channel
Frame service (separate container, on the Docker network; it reaches the simulator directly, never through the Windows `localhost:80` forward, which Docker Desktop dropped on a container recreate on Nov 1 — that port is only for a person watching the plant) captures the 3D view, adds configurable noise/lag/occlusion, emits timestamped frames. ZeroState: SAM 3.1 locates displays/equipment (SAM found 0 "valve" objects; valve = actuator under its display + layout map) → crop+upscale → Muse Spark strict-JSON read (single read in "must"; 3-read agreement is "should") → `unreadable` if invalid. Freeze detection in code (pixel hash). Lag measured, not assumed (the web page polls every 3 s). Not built, stated: people blurring (`redact.py`; simulator frames hold no people), a separate lag estimator (`align.py`; the lag is a measured threshold), 3-read voting (a "should"). Camera capture and model calls run in a worker thread; readings come back as logged events; LIVE-CAMERA compares each reading with the feedback logged at capture time and feeds only the with-camera track (decision 21). Display freeze (unchanged crop while the feedback changed beyond the lag) = FAIL on that track.

## 7. Gate
Plan → live → process checks. No model judge (decision 21): no model output can produce a pass or remove a block. Two tracks: data-only (drives the session) and with-camera (data-only worsened by any LIVE-CAMERA block). Verdict policy (Phase 1, `gate.py` pure + `session.py` timing): session warms in until every witness is GOOD (30 s wall, else ESCALATED); a step mark starts that step's evaluation, `pending` until its windows complete (pending is not a verdict); step k+1 can be marked only after step k is evaluated; FAIL → BLOCKED, else UNKNOWN → ESCALATED, else PASS; after the final step → NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF. Continuous monitor every 2 s re-checks QUALITY (all witnesses) and VALVE (each isolated point once its settle time has passed): FAIL → BLOCKED at once; UNKNOWN lasting > `monitor_unknown_grace_wall_s` → ESCALATED (grace never applies to FAIL). The verdict only gets worse on its own; a session refuses to start unless given a confirmed plan's hash. A step marked out of order or before the previous step is evaluated → PROC-SEQUENCE FAIL (Phase 2; marks before warm-in or after a terminal verdict are refused and logged). Verdict enum has no SAFE. Only a human signature closes. Every verdict carries: package version, rule ids+versions (live, plan, process, camera), threshold-file version, plan hash, confirmation record, plan-check override text, model ids (with-camera track), assumptions used.

## 8. Audit and evidence
SQLite append-only (triggers reject UPDATE/DELETE), each row stores SHA-256 of the previous row. Evidence tree JSON: goal → check → raw signal snapshot / frame hash. Ed25519 signing: "should".

## 9. Model roles (Meta)
Muse Spark: importer (typed text or sheet image/PDF → draft isolation list, human confirms) — must; reading displays from frames; plain-language explanation of logged findings (explain-only). SAM 3.1: locating displays/equipment. Never: deciding a pass, removing a block, or feeding the data-only verdict.

## 10. Failure behaviour
Plant data stops/stale → UNKNOWN → ESCALATED. Model API down / over budget → camera and explanations marked unavailable; data checks still run; verdict cannot be NO_DISCREPANCY if the envelope requires camera evidence. Unconfirmed or edited envelope → refuse to start.

## Stack
pydantic, networkx, pymodbus, asyncua, sqlite, FastAPI. QARTOD gross-range / spike / rate tests are a few lines each in our own code (cited to the QARTOD manual); `ioos_qc` dropped (it pulls in pandas + numpy for three formulas). Rejected: AAS/BaSyx core model, PLC4X, Node-RED, ML anomaly detectors in the gate, auto plan generation, rules engines (typed Python rules + versioned YAML instead).

## Model budget
SAM 3.1 ≈ $2.50 / 1k images; Muse Spark 1.3 $1.25 / $4.25 per M tokens. Checks free; models per frame read / explanation / import. Every call logged with cost to the credits ledger (path in config, default `D:\grfics\credits_log.md`).
