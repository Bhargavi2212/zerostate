# ZeroState — repository structure and build conventions

Status: revised Oct 31 2026 after independent review. Every file below has one job, one owner layer, and a test or eval that proves it. If a file isn't here, it doesn't get created without updating this doc.

## 0. Where things live
- `D:\grfics\` — GRFICS lab (Fortiphyd compose file, our old kill-test scripts, credits_log.md). **Not** part of the repo.
- `D:\grfics\zerostate\` — the ZeroState repo (public on GitHub). Everything below is relative to it.
- Fortiphyd code is never copied into our tree except the labelled patch in `plants/p1_grfics/patch/` (GPL-3.0, own LICENSE file).

## 1. Network reality (decides how ZeroState runs)
GRFICS publishes to Windows: simulation :80 (web/3D view + truth `/data/index.php`), PLC web :8080 (OpenPLC), EWS :6080, HMI :6081, kali :6088, caldera :8888, router :51820/udp. The PLC (192.168.95.2, Modbus) and simulation (192.168.95.45) are on `b-ics-net`; the HMI sits on `c-dmz-net` (192.168.90.x) behind the GRFICS router (192.168.95.200 / 192.168.90.200).
→ ZeroState runs as a container in the network namespace of a helper `zerostate-net`, which sits on `c-dmz-net` only (192.168.90.60), no bridge network, reading the PLC through the router. It can reach only the PLC's Modbus port: router rule + the helper's egress allowlist; ZeroState itself has no capabilities (decision 16). Read-only evidence: no write path + Suricata write-alert rule = 0, with a positive control from the operator container at .70 (decisions 11, 15). Started with a compose override (`deploy/docker-compose.zerostate.yml`), never by editing Fortiphyd's file.
Register map is known from source (ARCHITECTURE §1.2); Phase 0 confirms it, the address offset and the placeholder values with a live read-only scan.
Paths ZeroState must NOT reach: GRFICS :80 `/data/index.php`, the simulator socket :55555, remote I/O, PLC web :8080, `host.docker.internal`, other DMZ hosts, the router itself, the internet. Tested from inside the container.

## 2. Tree
```
zerostate/
├── README.md                      # what it is, how to run, results table (copied from eval output only)
├── CLAUDE.md                      # rules for coding agents (workflow, Ponytail, never-cut list)
├── LICENSE                        # Apache-2.0 (GRFICS patch keeps GPL-3.0 in its own folder)
├── pyproject.toml                 # package + deps; python >=3.11
├── .env.example                   # MODEL_API_KEY=  (name only, never a value)
├── .gitignore                     # .env, runs/, frames/, *.sqlite, __pycache__
├── .gitattributes                 # *.sh eol=lf (container scripts break with CRLF)
├── .dockerignore                  # keeps .venv, .git, runs/ out of build context
├── .pre-commit-config.yaml        # ruff, detect-secrets, fast pytest
├── .secrets.baseline              # detect-secrets baseline
├── docs/
│   ├── PROJECT.md  ARCHITECTURE.md  EVAL.md  CLAIMS.md  RESEARCH.md  STRUCTURE.md
│   ├── DECISIONS.md               # dated log: decision, options, why, who approved
│   ├── specs/                     # PHASE_<n>.md specs + PHASE_<n>_GATE.md outputs
│   └── MODEL_NOTES.md             # measured behaviour of Meta models (feeds README section)
├── deploy/
│   ├── docker-compose.zerostate.yml   # zerostate-net + zerostate (+ operator, frame service, egress proxy, p2 in later phases)
│   ├── Dockerfile                     # zerostate runtime image (python:3.13-slim, no capabilities, joins zerostate-net)
│   ├── Dockerfile.net                 # zerostate-net helper image (alpine + iptables)
│   ├── net_setup.sh                   # helper: route via router, OUTPUT allowlist (PLC:502 only), IPv6 drop, then sleep
│   ├── apply_router_rules.ps1         # idempotent router FORWARD rules + Suricata rule install; prints/checks chain order
│   ├── check_ids.ps1                  # counts sid 9100001 (ZeroState, must be 0) and 9100002 (operator, must be >0 per episode)
│   ├── suricata_zerostate.rules       # Modbus-write alert for .60 (ZeroState) and .70 (operator positive control)
│   └── egress/                        # Phase 2: proxy container; only allowed destination is the Meta API host
├── src/zerostate/                 # THE PRODUCT. Must never import plants/ or eval/.
│   ├── __init__.py  version.py    # semantic version stamped on every verdict
│   ├── config.py                  # loads settings + threshold YAMLs; rejects unknown keys
│   ├── models/                    # pydantic data types (no logic)
│   │   ├── envelope.py            # IsolationPlan (frozen, hashed: WorkScope, EnergySource, IsolationPoint, ProvingPoint, Segment, Witness, Relation, Assumption, HoldTest) + SessionState (statuses, Signature, step log; refs plan hash)
│   │   ├── signal.py              # Signal{tag, value, quality, source_ts, recv_ts}
│   │   ├── evidence.py            # Finding{rule_id, rule_version, status: PASS|FAIL|UNKNOWN, refs}, EvidenceTree
│   │   └── verdict.py             # Verdict enum: BLOCKED | ESCALATED | NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF (no SAFE)
│   ├── adapters/                  # read-only plant access
│   │   ├── base.py                # ReadOnlyAdapter protocol: read(), subscribe(), history(). No write anywhere.
│   │   ├── modbus.py              # pymodbus; function codes 1–4 only
│   │   ├── opcua.py               # asyncua; read/subscribe only
│   │   ├── replay.py              # plays a recorded episode (offline tests, re-scoring)
│   │   ├── freshness.py           # noise-loss staleness (wall clock), placeholder detection, dead source group
│   │   └── pi_web.py              # stretch
│   ├── importers/
│   │   ├── csv_import.py          # SAP WCM / Maximo-style isolation list + tag map → draft envelope
│   │   ├── muse_import.py         # PDF/image of P&ID or isolation sheet → draft envelope (Muse Spark)
│   │   └── confirm.py             # human confirmation → plan hash + signature; unconfirmed = unusable
│   ├── graph/
│   │   ├── build.py               # envelope → networkx graph
│   │   └── segments.py            # valve-bounded segment labelling (WNTR-style, own code)
│   ├── checks/                    # one file per rule; file name = rule ID suffix (PLAN-PATHS → plan/paths.py);
│   │   │                          # each exports RULE_ID, RULE_VERSION, check(...) -> Finding
│   │   ├── plan/   paths.py liveside.py boxedin.py software.py type.py proving.py mapping.py
│   │   ├── live/   quality.py alive.py relation.py upstream.py hold.py valve.py camera.py   # CUSUM lives in relation.py; __init__.py: window helpers + RULES registry
│   │   └── process/ sequence.py independence.py reset.py
│   ├── thresholds/default.yaml    # versioned generic thresholds; plant thresholds live with the plant (plants/<p>/thresholds.yaml → /app/config/<p>/), never in src/
│   ├── cli.py                     # `zs` console script: session start/stop, status, step done, sign, audit verify/export, replay
│   ├── camera/
│   │   ├── client.py              # receives frames from the frame service (no truth)
│   │   ├── locate.py              # SAM 3.1 boxes
│   │   ├── read.py                # crop+upscale, Muse Spark ×3, agreement
│   │   ├── freeze.py              # pixel-hash freeze detection (code)
│   │   ├── align.py               # camera↔data lag estimate and windowing
│   │   └── redact.py              # blur people before anything is stored or sent
│   ├── llm/
│   │   ├── client.py              # Meta API calls; every call logged with tokens + $ to credits ledger
│   │   ├── prompts/               # one .md per prompt, versioned
│   │   ├── explain.py             # plain-language reason per finding
│   │   └── judge.py               # optional second judge: may add a block, never remove one
│   ├── session.py                 # session lifecycle: warm-in → ready → steps (pending → evaluated) → verdict; continuous monitor; inbox/audit I/O
│   ├── gate.py                    # pure verdict policy: findings → verdict, monotonic, signature closes, verdict stamping (Phase 1); judge (Phase 2)
│   ├── audit/
│   │   ├── log.py                 # SQLite append-only, hash-chained rows
│   │   ├── sign.py                # Ed25519 verdict signatures
│   │   └── replay.py              # re-run gate on a logged session, must reproduce the verdict
│   └── api/
│       └── server.py              # FastAPI: sessions, live evidence (SSE), sign-off endpoint
├── ui/                            # operator screen (static HTML/JS served by api; tech: owner check §8)
├── plants/                        # TEST PLANTS. Never imported by src/zerostate.
│   ├── frame_service/             # separate container: captures 3D view, adds noise/lag/occlusion,
│   │                              # emits frames; stamps truth beside frames for eval only
│   ├── p1_grfics/
│   │   ├── envelope.yaml          # reactor maintenance plan; declares "positive isolation upstream assumed"
│   │   ├── relations.yaml         # GRFICS physics as data (valve-flow laws, Patm floor)
│   │   ├── modbus_map.yaml        # process_time_scale + tag → host/table/address/scale/freshness (from Phase 0 scan)
│   │   ├── scan_<date>.json       # Phase 0 live scan output (addresses, offset, placeholder values)
│   │   ├── operator.py            # performs steps via PLC manual mode (coil %QX0.0, %QW10–13) — NOT ZeroState
│   │   ├── Dockerfile.operator    # operator container, DMZ 192.168.90.70, router-allowed only PLC:502
│   │   ├── thresholds.yaml        # P1 plant thresholds (copied to /app/config/p1_grfics/)
│   │   ├── sim_socket.py          # ~20 lines piped into the simulation container: read/write the simulator socket (eval only)
│   │   ├── faults.py              # builds fault dicts, sends them via sim_socket.py (never the web API: it delays new faults 3 s)
│   │   ├── truth.py               # reads ground truth (GET localhost/data/index.php, runs on host) — eval only
│   │   └── patch/                 # GPL-3.0: transmitter noise (~0.1% span) + low-flow cutoff (realism; GRFICS already clamps), valve-feedback faults,
│   │                              # zero-position leak term, time scale; Dockerfile.derived, LICENSE, README listing every change
│   ├── p2_gasline/
│   │   ├── SPEC.md                # geometry, gas, valves, sensors, OPC UA node names, physics equations + sources
│   │   ├── model.py               # physics (ideal gas vessel/line, ISA-75 valve flow)
│   │   ├── server.py              # asyncua OPC UA server publishing sensors
│   │   ├── envelope.yaml  relations.yaml  opcua_nodes.yaml
│   │   ├── operator.py  faults.py  truth.py
│   │   ├── Dockerfile
│   │   └── validation/            # analytic blowdown comparison → overlay PNG + error %
│   └── p3_wntr/                   # stretch
├── eval/
│   ├── scenarios/                 # S0–S12, PC0–PC6 as YAML (plant, fault, onset range, severity range, expected verdicts)
│   ├── tools/timescale_test.py    # Phase 1: time-scale stability runs (×1 / ×10 / ×5) → results/timescale_<date>.json
│   ├── seal.py                    # draws tune/score seed ranges; writes manifest OUTSIDE repo; commits SHA-256(salt+manifest)
│   ├── sealed_hash.txt            # committed hash only
│   ├── claims.yaml                # claim id → tests → result key → exact README sentence
│   ├── runner.py                  # runs on the host (sim via localhost:80, operator via docker exec); one episode: check router+IDS rules, note eve.json byte offset → plant up → operator → faults → zerostate → record → re-check rules (missing = episode invalid); IDS alerts counted after the offset (file shrank = rotated → from 0)
│   ├── baselines/  gauge_rule.py  muse_alone.py
│   ├── plan_cases/                # generated envelopes with planted errors; labels in sealed manifest
│   ├── plan_benchmark.py  run_benchmark.py  read_accuracy.py  p2_validation.py  importer_accuracy.py
│   ├── score.py                   # opens seal, compares to truth, Wilson CIs
│   ├── claims_audit.py            # reads claims.yaml: tests exist + pass, result keys exist, README sentence matches
│   └── results/                   # committed outputs (json + md) with commit hash: timescale_<date>.json, smoke_p1_<date>.md, …
├── tests/
│   ├── test_readonly.py           # no plant-protocol write call anywhere; only adapters/ import pymodbus/asyncua; no write*/set* methods in adapters
│   ├── test_firewall.py           # AST scan: src/zerostate imports nothing from plants/ or eval/, no GRFICS web URL
│   ├── test_models.py             # no SAFE; extra fields rejected; plan hash stable/changes; session edits don't touch plan hash
│   ├── test_modbus_adapter.py     # in-process Modbus server: scaled values; server down → BAD
│   ├── test_freshness.py          # placeholder, STALE, constant_ok_raw, dead group (injectable clock)
│   ├── test_plant_map.py          # map loads; every plan tag exists in the map
│   ├── test_modbus_scan.py        # scan script offset check
│   ├── test_timescale_judge.py    # time-scale pass/fail criteria (eval/tools/timescale_test.py)
│   ├── test_gate.py               # no SAFE; FAIL beats UNKNOWN; monotonic; signature closes; stamping; no never-say words (judge + refusals: Phase 2)
│   ├── test_session.py            # warm-in, plan-hash refusal, pending, step order, settle before monitoring, UNKNOWN grace, stop
│   ├── test_operator.py           # operator: setpoints before coil, readback mismatch aborts, manual off restores defaults
│   ├── conftest.py                # shared in-process Modbus server fixture (adapter + operator tests)
│   ├── test_audit_chain.py  test_replay.py  test_importer_gate.py  test_plants_only_diff.py
│   ├── net/test_container_isolation.py   # run inside container: only PLC:502 reachable; truth, host ports, DMZ, router, internet not; app can't change net config
│   ├── checks/                    # test_<rule>.py per rule (test_paths.py … test_reset.py), a passing and a failing case each; test_timescale_invariance.py
│   ├── live/                      # marker `live`, run from the host against the lab: test_patch.py, test_operator_net.py
│   │                              # tests/checks/synth.py: synthetic P1 windows (vent model, 4 Hz polls) for rule tests
│   └── fixtures/                  # small recorded episodes for offline tests
└── scripts/
    ├── modbus_scan.py             # Phase 0: map GRFICS registers (read-only)
    └── capture_frames.py
```

## 3. Boundaries (enforced by tests, not by convention)
| Rule | Enforced by |
|---|---|
| `src/zerostate` never imports `plants/` or `eval/` | tests/test_firewall.py |
| No code in `src/zerostate` references GRFICS web API URL | tests/test_firewall.py |
| No write path in any adapter | tests/test_readonly.py |
| ZeroState container reaches only PLC:502 (no truth, host ports, DMZ peers, router, internet) | tests/net/test_container_isolation.py |
| No Modbus write from ZeroState's IP; IDS proven to see writes | deploy/check_ids.ps1 (9100001 = 0, 9100002 > 0 per episode) |
| P1→P2 changes only plants/* | tests/test_plants_only_diff.py (CI) |
| Only `plants/*/truth.py` and `eval/` read ground truth | tests/test_firewall.py |
| Every check exports RULE_ID + RULE_VERSION and has a pass and a fail test | tests/checks/ + claims_audit |
| Every LLM call goes through `llm/client.py` and is logged with cost | test + grep in claims_audit |
| No secret in repo | .gitignore + pre-commit secret scan |

## 4. Claim → code → proof map
| Claim | Code | Proof |
|---|---|---|
| C1 read-only, reaches only PLC Modbus | adapters/, deploy/ network rules | test_readonly, test_firewall, net/test_container_isolation, check_ids |
| C2 two plants, plant files only | plants/p1, p2 | test_plants_only_diff + run_benchmark |
| C3 plan errors | checks/plan/* | plan_benchmark |
| C4 instrument evidence | checks/live/alive, relation | test_alive, test_relation + S1/S2/S3 |
| C5/C6 misses, false blocks | gate + all checks | run_benchmark + score |
| C7 camera reading | camera/*, plants/frame_service | read_accuracy |
| C8 lying feedback | checks/live/relation, valve, camera | S8 |
| C9 stale data never passes | adapters/freshness, checks/live/quality | test_freshness, test_quality + S12 |
| C10 gate rules | models/verdict, gate, llm/judge | test_gate |
| C11 hash chain + replay | audit/* | test_audit_chain, test_replay |
| C12 P2 implementation check | plants/p2_gasline/model | p2_validation |
| C13 process rules | checks/process/* | test_sequence, test_independence, test_reset + S7 |
| C14 importer | importers/* | test_importer_gate, importer_accuracy |

## 5. Conventions
- Build workflow: this planning session writes one spec per phase in `docs/specs/PHASE_<n>.md` (what + acceptance tests + gate, never how). VS Code Claude Code with Ponytail plans → codes → tests from the spec. Rules for coding agents: `CLAUDE.md` at repo root (incl. the never-cut list).
- Python ≥3.11 in a repo venv: `python -m venv .venv`; `.venv\Scripts\Activate.ps1`; `pip install -e .[dev]` (Windows/PowerShell). Runtime in Docker with pinned deps.
- Git: one commit per spec item or smaller, never with failing tests; branch per phase named `p<n>-work` (never the same name as a tag); nothing is pushed to `main` directly, everything lands through a pull request; tag `phase-<n>` only after the gate passes and the PR is merged, then delete the work branch; gate output saved in `docs/specs/PHASE_<n>_GATE.md`. Pre-commit: ruff, detect-secrets, fast pytest.
- Formatting/lint: ruff; tests: pytest; types: pydantic models, mypy on src/ (best effort).
- Time: all timestamps UTC, ISO-8601; plant source timestamp kept separate from receive timestamp.
- IDs: rule ids exactly as in ARCHITECTURE (`PLAN-PATHS`, `LIVE-ALIVE`, `PROC-RESET` …), version in the separate `RULE_VERSION` field; file name = lower-case suffix (`checks/live/alive.py`), test = `tests/checks/test_alive.py`; scenario ids as in EVAL.md; claim ids as in CLAIMS.md.
- Clocks: process thresholds in process-seconds (`*_process_s`, converted with the plant's `process_time_scale`); freshness windows in wall-clock seconds (`*_wall_s`).
- Versioning: package semver; each rule has its own version; thresholds YAML has a version; all three stamped on every verdict.
- Commit messages: `P<phase>-<item> <what> (<claim ids>)`.

## 6. Failure behaviour (product rules)
- Plant data stops / stale / bad quality → affected findings UNKNOWN → verdict ESCALATED, never pass.
- Model API down or over budget → camera and explanations marked unavailable; gate still runs on data; verdict can't be NO_DISCREPANCY if the envelope requires camera evidence.
- Unconfirmed or edited envelope (hash mismatch) → refuse to start.

## 7. What moves from D:\grfics into the repo
- `zerostate_test.py` → reference only (kill test, Oct 27); not copied. Its lessons go to MODEL_NOTES.md.
- `log_plant.py` → superseded by `adapters/` + `eval/runner.py`.
- `credits_log.md` stays canonical at D:\grfics; `llm/client.py` appends to it.

## 8. Owner decisions needed
Operator page tech — plain HTML/JS served by FastAPI (suggested, fastest) vs React. (Everything else is decided: PROJECT.md decisions 1–20.)
