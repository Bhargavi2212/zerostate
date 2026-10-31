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
 Egress proxy (Phase 2+): the only route from ZeroState to the Meta API; ZeroState itself has no internet.
```

## 1. Adapters (read-only)
- Interface exposes only `read`, `subscribe`, `history`. No write method exists in our code. (The pymodbus library itself can write; read-only at the protocol level is enforced by network policy — §1.3.)
- Modbus: pymodbus, function codes 1–4 only. OPC UA: asyncua, read-only user. PI Web API: stretch.
### 1.1 Data quality — what "good" means
- **Modbus has no source timestamps, and GRFICS serves stale data with successful reads**: before the simulator connects, remote I/O registers hold placeholder values (`modbusdevice.py`); if the simulator link dies, registers keep their last values. So read success ≠ good quality.
- Freshness is inferred from **process noise** (decision 13): measured values carry transmitter noise (~0.1% of span; added by our patch on P1, part of the model on P2), so a healthy reading changes every poll. A signal unchanged beyond `max_static_wall_s` (wall clock) is `STALE`. Signals that are legitimately flat (valves at end stops, flows at low-flow cutoff) are allowed by `constant_ok_raw` and stay GOOD but expose how long they've been static. A source group is dead when every noisy tag in it is static. Which values may legitimately sit still is per tag (`constant_ok_raw`: `any` or a list of raw values, e.g. `[0]` for flows at cutoff). The patch's low-flow cutoff is for realism (real flow transmitters have one); GRFICS already clamps raw values to 0–65535. Placeholder **raw values** recorded by the Phase 0 scan → `UNKNOWN`. This catches a break anywhere along sim → I/O → PLC → network, because the noise must survive the whole path. Freeze detection therefore depends on our noise model, and results say so.
- OPC UA: StatusCode and SourceTimestamp used directly; Bad/Uncertain/old → `UNKNOWN`.
- Any `UNKNOWN`/`STALE` evidence a check depends on → that check returns UNKNOWN → verdict cannot be NO_DISCREPANCY.
### 1.2 P1 register map (from GRFICS source; confirm by live scan in Phase 0, incl. address offset)
Remote I/O (port 502, unit id ignored): Feed1 .10, Feed2 .11, Purge .12, Product .13 → IR1 valve position (0–100%, **true position** — source reads `state.*_valve_pos`), IR2 flow (full scale 1000 / 500 / 2000 / 500); HR1 valve command. Tank .14 → IR1 pressure (0–3200 kPa), IR2 level (0–100%). Analyzer .15 → IR1–3 A/B/C. PLC .2 mirrors them at %IW100–112, commands %QW100–103; manual mode coil %QX0.0, manual setpoints %QW10–13. **No temperature, gas detector or e-stop register exists.**
### 1.3 Firewall (network level + code level)
- Network: the ZeroState container can reach only the PLC's Modbus port (P1) / the OPC UA endpoint (P2), enforced twice (decision 16): (1) router FORWARD rules allow .60 → PLC:502 and drop everything else from .60; (2) an egress allowlist (OUTPUT policy DROP; IPv4 and IPv6) set by a separate helper container `zerostate-net`, because same-subnet DMZ traffic and traffic to the router itself never pass FORWARD. ZeroState joins the helper's network namespace with `cap_drop: ALL`, so even root inside ZeroState can't change routes or rules. ZeroState joins no bridge network (a bridge reaches Windows-published ports via `host.docker.internal`, including truth :80 and OpenPLC's web UI :8080). Tests from inside the container must fail to connect to: GRFICS truth :80 and :55555 (simulator JSON socket, carries truth and fault flags), remote I/O, PLC web :8080, `host.docker.internal` :80/:8080, other DMZ hosts, the router, and the internet.
- The router cannot filter Modbus by function code (Suricata runs IDS-only), so writes are evidenced, not blocked, at network level: a Suricata rule alerts on any Modbus write from ZeroState's IP (sid 9100001, must stay 0). The same rule for the operator container's IP (sid 9100002) must fire every episode — a positive control proving the rule and the IDS's view of the traffic (decision 15). The episode runner checks the router rules and Suricata rules are present before and after every episode; missing → episode invalid.
- Internet (Phase 2+): ZeroState never has it. Meta API calls go through an egress proxy container that may reach only `https://api.meta.ai/v1` (pinned in config); ZeroState reaches the proxy over an internal-only Docker network (decision 14).
- Code: `src/zerostate` imports nothing from `plants/` or `eval/` and contains no truth URLs (AST test).
- The frame service is outside ZeroState. On P1 it necessarily renders truth; that is declared, not hidden.

## 2. Isolation envelope (plant-agnostic data model)
Pydantic schema, YAML, keyed by plant tags; field names follow SAP PM WCM and IBM Maximo HSE.
- `WorkScope{equipment, task, permit_ids}`; `EnergySource{tag, type, max_magnitude}`
Two halves (decision 18): **`IsolationPlan`** (everything below except `SessionState`) is frozen and hashed once a person confirms it; **`SessionState`** holds what changes during the job and references the plan hash.
- `IsolationPoint{tag, device: block_valve|control_valve|blind|spade|spool_removed|breaker, isolation_type: positive|proved|non_proved, normal_state, required_state, apply_seq, remove_seq, lock_id, tag_id}`
- `ProvingPoint{tag, kind: vent|bleed|drain|test_point, proves: [IsolationPoint], discharges_to}`
- `Segment{id, members, bounded_by, vents}`; plant graph in NetworkX.
- `Witness{segment, signal_ref, role, side: work|upstream|between_blocks, redundancy_group}`
- `Relation{type, signals, params}` — plant physics as data, e.g. `valve_sqrt_law: F = k·x·sqrt(P − p_floor)` (P1: k_purge 0.352, k_product 0.0417, p_floor 100 kPa).
- `Assumption{text, scope}` — declared out-of-scope facts (e.g. P1 "positive isolation upstream assumed"); printed in every verdict that relies on them.
- `HoldTest{hold_process_s, window_process_s, max_rise, upstream_min}` — fixed before the run. Process-seconds, converted to wall time with the plant's declared `process_time_scale` (decision 17). The rise is the mean of the last window minus the mean of the first window, never single noisy samples; `max_rise` sits above the noise band of a window mean.
- `SessionState{plan_hash, point_status: {tag → ITG|ETG|ETUG|EUG}, signatures: [Signature], step_log: [step, ts]}`
- `Signature{role: planner|approver|installer|verifier|prover|receiver, person, ts}`
A plan is usable only after human confirmation (hash recorded); any edit to the plan invalidates it. Session changes never touch the plan hash.

## 3. Plan checks (deterministic, graph)
| Rule id | Check | Real case | Test plant |
|---|---|---|---|
| PLAN-PATHS | with isolation points in required state, no path from any source to work segment | missed line (HSG253) | P2, plan set |
| PLAN-LIVESIDE | no isolation device inside the energised boundary | LyondellBasell 2021 | P2, plan set |
| PLAN-BOXEDIN | closed volume with heat source and no relief path | Williams 2013 | P2 (heater), plan set |
| PLAN-SOFTWARE | isolation by control valve / software deselect only | HSG253 case; 1910.147(b) | P1 (fires by design), plan set |
| PLAN-TYPE | isolation type vs hazard (non-proved on hazardous service) | HSG253 | P1, P2 |
| PLAN-PROVING | proved isolation has a proving point; bleed not into pressurised header | IChemE LPB 250 | P2 |
| PLAN-MAPPING | every tag exists; witnesses on correct side | Pemex 2024, Formosa 2004 | P1, P2 |
Shared-point conflicts across permits: stretch (needs multiple envelopes).

## 4. Live checks (deterministic)
| Rule id | Check | Notes |
|---|---|---|
| LIVE-QUALITY | fresh, not placeholder, gross range (ioos_qc) | §1.1 |
| LIVE-ALIVE | instrument moved consistently with a known disturbance (the depressurisation) before being trusted; flatline gated on active inputs | "after" check only where a post-hold disturbance exists (P2 bleed crack). On P1 a gauge frozen after the vent at the true value is caught only by noise loss (LIVE-QUALITY) — depends on our noise model, labelled in EVAL. |
| LIVE-RELATION | residual between signal and physics relation / redundant sensor (2-of-3 where available); CUSUM for slow drift (inside this rule) | P1 redundancy = pressure vs purge/product flow laws only while valves open and P > ~150 kPa |
| LIVE-UPSTREAM | upstream pressure present during hold (not a dry test) | P2 only (P1 has no upstream sensor) |
| LIVE-HOLD | no rise beyond `max_rise` over `hold_process_s` | |
| LIVE-VALVE | command vs position feedback; commanded closed with flow above the low-flow cutoff | needs patch on P1 |
| LIVE-CAMERA | camera reading agrees with data within measured lag window | idealised on P1 |
| LIVE-REPLAY | repeated window / autocorrelation | stretch |
Transients: "unexpected change" alarms suppressed during commanded transients; invariants never suppressed. Generic checks for gas detectors / temperature exist in the design only when a plant has those signals; neither test plant does, so they are not built or claimed.

## 5. Process checks
Fixed step order from the envelope, stop at first failure (PROC-SEQUENCE); installer ≠ verifier ≠ prover (PROC-INDEPENDENCE); temporary de-isolation (ETUG) resets affected segments (PROC-RESET). Re-prove interval: stretch.

## 6. Camera channel
Frame service (separate container) captures the 3D view, adds configurable noise/lag/occlusion, emits timestamped frames. ZeroState: SAM 3.1 locates displays/equipment (SAM found 0 "valve" objects; valve = actuator under its display + layout map) → crop+upscale → Muse Spark strict-JSON read (single read in "must"; 3-read agreement is "should") → `unreadable` if invalid. Freeze detection in code (pixel hash). Lag measured, not assumed (the web page polls every 3 s). People blurred before storage/sending.

## 7. Gate
Plan → live → process checks → optional Muse Spark judge over the evidence tree (may add a block, never remove one). Verdict enum has no SAFE. 3 refusals on a step → ESCALATED. Only a human signature closes. Every verdict carries: package version, rule ids+versions, threshold-file version, plan hash, model ids (version-pinned API models), assumptions used.

## 8. Audit and evidence
SQLite append-only (triggers reject UPDATE/DELETE), each row stores SHA-256 of the previous row. Evidence tree JSON: goal → check → raw signal snapshot / frame hash. Ed25519 signing: "should".

## 9. Model roles (Meta)
Muse Spark: importer (isolation sheet → draft envelope, human confirms) — must; reading displays from frames; plain-language explanation of each block; optional judge. SAM 3.1: locating displays/equipment. Never: deciding a pass.

## 10. Failure behaviour
Plant data stops/stale → UNKNOWN → ESCALATED. Model API down / over budget → camera and explanations marked unavailable; data checks still run; verdict cannot be NO_DISCREPANCY if the envelope requires camera evidence. Unconfirmed or edited envelope → refuse to start.

## Stack
pydantic, networkx, pymodbus, asyncua, ioos_qc, numpy/pandas, sqlite, FastAPI. Rejected: AAS/BaSyx core model, PLC4X, Node-RED, ML anomaly detectors in the gate, auto plan generation, rules engines (typed Python rules + versioned YAML instead).

## Model budget
SAM 3.1 ≈ $2.50 / 1k images; Muse Spark 1.3 $1.25 / $4.25 per M tokens. Checks free; models per frame read / explanation / import. Every call logged with cost to the credits ledger (path in config, default `D:\grfics\credits_log.md`).
