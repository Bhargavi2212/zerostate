# ZeroState â€” repository structure and build conventions

Status: revised Oct 31 2026 after independent review. Every file below has one job, one owner layer, and a test or eval that proves it. If a file isn't here, it doesn't get created without updating this doc.

## 0. Where things live
- `D:\grfics\` â€” GRFICS lab (Fortiphyd compose file, our old kill-test scripts, credits_log.md). **Not** part of the repo.
- `D:\grfics\zerostate\` â€” the ZeroState repo (public on GitHub). Everything below is relative to it.
- Fortiphyd code is never copied into our tree except the labelled patch in `plants/p1_grfics/patch/` (GPL-3.0, own LICENSE file).

## 1. Network reality (decides how ZeroState runs)
GRFICS publishes to Windows: simulation :80 (web/3D view + truth `/data/index.php`), PLC web :8080 (OpenPLC), EWS :6080, HMI :6081, kali :6088, caldera :8888, router :51820/udp. The PLC (192.168.95.2, Modbus) and simulation (192.168.95.45) are on `b-ics-net`; the HMI sits on `c-dmz-net` (192.168.90.x) behind the GRFICS router (192.168.95.200 / 192.168.90.200).
â†’ ZeroState runs as a container in the network namespace of a helper `zerostate-net`, which sits on `c-dmz-net` only (192.168.90.60), no bridge network, reading the PLC through the router. It can reach only the PLC's Modbus port: router rule + the helper's egress allowlist; ZeroState itself has no capabilities (decision 16). Read-only evidence: no write path + Suricata write-alert rule = 0, with a positive control from the operator container at .70 (decisions 11, 15). Started with a compose override (`deploy/docker-compose.zerostate.yml`), never by editing Fortiphyd's file.
Register map is known from source (ARCHITECTURE Â§1.2); Phase 0 confirms it, the address offset and the placeholder values with a live read-only scan.
Phase 2 adds three allowed destinations, each with a net test: P2's OPC UA server (192.168.95.50:4840, through the router), the model proxy (172.30.0.2:8888) and the frame service (172.30.0.3:8080), both on the internal network `zs-internal` (no internet).
Paths ZeroState must NOT reach: GRFICS :80 `/data/index.php`, the simulator socket :55555, remote I/O, PLC web :8080, `host.docker.internal`, other DMZ hosts, the router itself, the internet. Tested from inside the container.

## 2. Tree
```
zerostate/
â”œâ”€â”€ README.md                      # what it is, how to run, results table (copied from eval output only)
â”œâ”€â”€ CLAUDE.md                      # rules for coding agents (workflow, Ponytail, never-cut list)
â”œâ”€â”€ LICENSE                        # Apache-2.0 (GRFICS patch keeps GPL-3.0 in its own folder)
â”œâ”€â”€ pyproject.toml                 # package + deps; python >=3.11
â”œâ”€â”€ .env.example                   # MODEL_API_KEY=  (name only, never a value)
â”œâ”€â”€ .gitignore                     # .env, runs/, frames/, *.sqlite, __pycache__
â”œâ”€â”€ .gitattributes                 # *.sh eol=lf (container scripts break with CRLF)
â”œâ”€â”€ .dockerignore                  # keeps .venv, .git, runs/ out of build context
â”œâ”€â”€ .pre-commit-config.yaml        # ruff, detect-secrets, fast pytest
â”œâ”€â”€ .secrets.baseline              # detect-secrets baseline
â”œâ”€â”€ docs/
â”‚   â”œâ”€â”€ PROJECT.md  ARCHITECTURE.md  EVAL.md  CLAIMS.md  RESEARCH.md  STRUCTURE.md
â”‚   â”œâ”€â”€ API.md                     # Phase 2: HTTP API contract (plans, sessions, explain, voice) the Phase 3 console builds on
â”‚   â”œâ”€â”€ BUNDLE.md                  # Phase 2: episode bundle schema the public replay viewer reads
â”‚   â”œâ”€â”€ DECISIONS.md               # dated log: decision, options, why, who approved
â”‚   â”œâ”€â”€ specs/                     # PHASE_<n>.md specs + PHASE_<n>_GATE.md outputs
â”‚   â””â”€â”€ MODEL_NOTES.md             # measured behaviour of Meta models (feeds README section)
â”œâ”€â”€ deploy/
â”‚   â”œâ”€â”€ docker-compose.zerostate.yml   # zerostate-net + zerostate (+ operator, frame service, egress proxy, zs-api + zs-api-net, p2 in later phases); volumes zs-data, zs-audit
â”‚   â”œâ”€â”€ Dockerfile                     # zerostate runtime image (python:3.13-slim, no capabilities, joins zerostate-net)
â”‚   â”œâ”€â”€ Dockerfile.net                 # zerostate-net / zs-api-net helper image (alpine + iptables; net_setup.sh, api_net.sh)
â”‚   â”œâ”€â”€ net_setup.sh                   # helper: route via router, OUTPUT allowlist (PLC:502, P2 OPC UA :4840, proxy :8888, frames :8080), IPv6 drop, then sleep
â”‚   â”œâ”€â”€ api_net.sh                     # zs-api-net helper: OUTPUT allowlist = proxy only (+ replies to 127.0.0.1:8090)
â”‚   â”œâ”€â”€ apply_router_rules.ps1         # idempotent router FORWARD rules + Suricata rule install; prints/checks chain order
â”‚   â”œâ”€â”€ check_ids.ps1                  # counts sid 9100001 (ZeroState, must be 0) and 9100002 (operator, must be >0 per episode)
â”‚   â”œâ”€â”€ suricata_zerostate.rules       # Modbus-write alert for .60 (ZeroState) and .70 (operator positive control)
â”‚   â””â”€â”€ proxy/                         # zs-proxy: tinyproxy, CONNECT api.meta.ai:443 only (Dockerfile, tinyproxy.conf, filter)
â”œâ”€â”€ src/zerostate/                 # THE PRODUCT. Must never import plants/ or eval/.
â”‚   â”œâ”€â”€ __init__.py  version.py    # semantic version stamped on every verdict
â”‚   â”œâ”€â”€ config.py                  # loads settings + threshold YAMLs; rejects unknown keys
â”‚   â”œâ”€â”€ models/                    # pydantic data types (no logic)
â”‚   â”‚   â”œâ”€â”€ envelope.py            # IsolationPlan (frozen, hashed: WorkScope, EnergySource, IsolationPoint, ProvingPoint, Segment, Witness, Relation, Assumption, HoldTest, Step, camera) + IsolationList (authored) + SessionState (statuses, Signature, step log; refs plan hash)
â”‚   â”‚   â”œâ”€â”€ plant_map.py           # PlantMap: nodes (source, vessel, valve, vent/bleed, relief, heater, instrument), pipes, plan_defaults
â”‚   â”‚   â”œâ”€â”€ signal.py              # Signal{tag, value, quality, source_ts, recv_ts}
â”‚   â”‚   â”œâ”€â”€ evidence.py            # Finding{rule_id, rule_version, status: PASS|FAIL|UNKNOWN, refs}, EvidenceTree
â”‚   â”‚   â””â”€â”€ verdict.py             # Verdict enum: BLOCKED | ESCALATED | NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF (no approval member)
â”‚   â”œâ”€â”€ adapters/                  # read-only plant access
â”‚   â”‚   â”œâ”€â”€ base.py                # ReadOnlyAdapter protocol: read(), subscribe(), history(). No write anywhere.
â”‚   â”‚   â”œâ”€â”€ modbus.py              # pymodbus; function codes 1â€“4 only
â”‚   â”‚   â”œâ”€â”€ opcua.py               # asyncua; read/subscribe only
â”‚   â”‚   â”œâ”€â”€ replay.py              # plays a recorded episode (offline tests, re-scoring)
â”‚   â”‚   â”œâ”€â”€ freshness.py           # noise-loss staleness (wall clock), placeholder detection, dead source group
â”‚   â”‚   â””â”€â”€ pi_web.py              # stretch
â”‚   â”œâ”€â”€ importers/                 # every route â†’ IsolationList draft; a person confirms
â”‚   â”‚   â”œâ”€â”€ csv_import.py          # SAP WCM / Maximo-style isolation export, exact parse, no model
â”‚   â”‚   â”œâ”€â”€ text_import.py         # typed text â†’ Muse Spark strict JSON (extract only; unclear = null)
â”‚   â”‚   â”œâ”€â”€ image_import.py        # sheet photo / PDF page 1 (pypdfium2) â†’ Muse Spark strict JSON
â”‚   â”‚   â”œâ”€â”€ draft.py               # /data/drafts/<id>.json â†’ build.merge â†’ plan checks; nulls block confirmation
â”‚   â”‚   â””â”€â”€ confirm.py             # a person confirms â†’ plan hash + record (plants/<p>/confirmed.yaml or /data/plans/); agents never run it
â”‚   â”œâ”€â”€ graph/
â”‚   â”‚   â”œâ”€â”€ build.py               # plant map â†’ networkx graph; merge(map, list) â†’ IsolationPlan (deterministic)
â”‚   â”‚   â””â”€â”€ regions.py             # energised region given the closed points (one helper for the plan rules)
â”‚   â”œâ”€â”€ checks/                    # one file per rule; file name = rule ID suffix (PLAN-PATHS â†’ plan/paths.py);
â”‚   â”‚   â”‚                          # each exports RULE_ID, RULE_VERSION, check(...) -> Finding
â”‚   â”‚   â”œâ”€â”€ plan/   paths.py liveside.py boxedin.py software.py type.py proving.py mapping.py
â”‚   â”‚   â”œâ”€â”€ live/   quality.py alive.py relation.py upstream.py hold.py valve.py camera.py   # CUSUM lives in relation.py; __init__.py: window helpers; camera.py feeds only the with-camera track
â”‚   â”‚   â””â”€â”€ process/ sequence.py independence.py reset.py
â”‚   â”œâ”€â”€ thresholds/default.yaml    # versioned generic thresholds; plant thresholds live with the plant (plants/<p>/thresholds.yaml â†’ /app/config/<p>/), never in src/
â”‚   â”œâ”€â”€ cli.py                     # `zs`: session start (incl. --from-inbox: a start queued by the API)/stop, status, step done/verify/reopen, sign (--outcome), plan import/show/confirm, audit verify/export, replay, api; camera worker thread
â”‚   â”œâ”€â”€ camera/
â”‚   â”‚   â”œâ”€â”€ client.py              # fetches frames from the frame service (172.30.0.3:8080; no truth)
â”‚   â”‚   â”œâ”€â”€ locate.py              # SAM 3.1 boxes matched to display_map regions
â”‚   â”‚   â”œâ”€â”€ read.py                # crop + upscale, single Muse Spark read (3-read voting is a should)
â”‚   â”‚   â”œâ”€â”€ freeze.py              # freeze detection in code: average hash of each display region (frame noise defeats an exact pixel hash)
â”‚   â”‚   â””â”€â”€ track.py               # the with-camera track: worker-thread bursts (3 frames, 2 s apart), camera_reading (with SAM box) / camera evaluation / with_camera verdict events; saves each frame to /data/frames/<session>/<sha256>.jpg
â”‚   â”‚                              # not built: align.py (lag is a measured threshold), redact.py (no people in simulator frames)
â”‚   â”œâ”€â”€ llm/
â”‚   â”‚   â”œâ”€â”€ client.py              # the only Meta API caller: via zs-proxy (explicit), spark_json / sam_boxes, ledger /data/credits.jsonl, budget stop ZS_BUDGET_USD
â”‚   â”‚   â”œâ”€â”€ prompts/               # one .md per prompt, versioned (import_list_v1.md: list from text; transcribe_sheet_v1.md: verbatim sheet transcript for the photo route; read_display_v1.md: one display crop -> {value, readable}; read_display_v2.md: same, right-aligned single digits incl. 0 are complete)
â”‚   â”‚   â””â”€â”€ explain.py             # Phase 3: plain-language answer from logged findings only (never changes a verdict)
â”‚   â”œâ”€â”€ session.py                 # session lifecycle: warm-in â†’ ready â†’ steps (pending â†’ evaluated) â†’ verdict; continuous monitor; inbox/audit I/O
â”‚   â”œâ”€â”€ gate.py                    # pure verdict policy: findings â†’ verdict, monotonic, signature closes, verdict stamping; no model judge
│   ├── wording.py                 # the one never-say checker (PROJECT.md list + `\bsafe\b` + banned labels); `python -m zerostate.wording <files>`; eval, site and tests import it
â”‚   â”œâ”€â”€ audit/
â”‚   â”‚   â”œâ”€â”€ log.py                 # SQLite append-only, hash-chained rows
â”‚   â”‚   â”œâ”€â”€ sign.py                # Ed25519 verdict signatures
â”‚   â”‚   â””â”€â”€ replay.py              # re-run gate on a logged session, must reproduce the verdict
â”‚   â””â”€â”€ api/                       # __init__.py + server.py + replay.py (bundles v1/v2 -> session events for `zs api --replay`)
â”‚       â””â”€â”€ server.py              # FastAPI (zs-api, 127.0.0.1:8090): plans, drafts, sessions list/start/detail, SSE, camera evidence + saved frames, voice read-back, inbox actions; serves ui/ at /ui/; audit read-only; playwright-test guard
â”œâ”€â”€ ui/                            # Phase 3 operator console (static, served by zs-api)
â”‚   â”œâ”€â”€ index.html  style.css      # one page, ISA-101 greys; no framework, no build step, no CDN
â”‚   â”œâ”€â”€ app.js  lib.js             # router (#/ sessions, #/new, #/job/<id>) + session list; DOM/API helpers, verdict wording, "test harness" names
â”‚   â”œâ”€â”€ intake.js                  # screen A: Type/Upload/CSV import, editable draft table, plan check, Confirm dialog
â”‚   â”œâ”€â”€ job.js                     # screens B + C: assumptions strip, two-track banner, steps, findings, camera panel, explain, sign; SSE
â”‚   â””â”€â”€ plant.js  chart.js         # SVG plant view laid out from the plant map; evidence charts with vent/hold windows shaded
â”œâ”€â”€ site/                          # Phase 3 public replay viewer + results (Vercel, static, reads committed bundles only)
â”œâ”€â”€ plants/                        # TEST PLANTS. Never imported by src/zerostate.
â”‚   â”œâ”€â”€ frame_service/             # zs-frames: headless Chromium renders the 3D view; GET /frame?view=<views.yaml name> only;
â”‚   â”‚                              # JPEG + noise; truth sidecar to a volume ZeroState never mounts (eval only)
â”‚   â”‚                              # server.py, Dockerfile, views.yaml (named views), display_map.yaml (view -> display region -> point; copied into the zerostate image as config)
â”‚   â”œâ”€â”€ p1_grfics/
â”‚   â”‚   â”œâ”€â”€ envelope.yaml          # reactor maintenance plan (hand-written live plan); declares "positive isolation upstream assumed"
â”‚   â”‚   â”œâ”€â”€ plant_map.yaml         # Phase 2: P1 plant graph for the plan checks (expected: BLOCKED by PLAN-SOFTWARE + PLAN-TYPE)
â”‚   â”‚   â”œâ”€â”€ confirmed.yaml         # plan hashes confirmed by a person (written by `zs plan confirm` run by the owner, never by an agent)
â”‚   â”‚   â”œâ”€â”€ relations.yaml         # GRFICS physics as data (valve-flow laws, Patm floor)
â”‚   â”‚   â”œâ”€â”€ modbus_map.yaml        # process_time_scale + tag â†’ host/table/address/scale/freshness (from Phase 0 scan)
â”‚   â”‚   â”œâ”€â”€ scan_<date>.json       # Phase 0 live scan output (addresses, offset, placeholder values)
â”‚   â”‚   â”œâ”€â”€ operator.py            # performs steps via PLC manual mode (coil %QX0.0, %QW10â€“13) â€” NOT ZeroState
â”‚   â”‚   â”œâ”€â”€ Dockerfile.operator    # operator container, DMZ 192.168.90.70, router-allowed only PLC:502
â”‚   â”‚   â”œâ”€â”€ thresholds.yaml        # P1 plant thresholds (copied to /app/config/p1_grfics/)
â”‚   â”‚   â”œâ”€â”€ sim_socket.py          # ~20 lines piped into the simulation container: read/write the simulator socket (eval only)
â”‚   â”‚   â”œâ”€â”€ faults.py              # builds fault dicts, sends them via sim_socket.py (never the web API: it delays new faults 3 s)
â”‚   â”‚   â”œâ”€â”€ truth.py               # reads ground truth (GET localhost/data/index.php, runs on host) â€” eval only
â”‚   â”‚   â””â”€â”€ patch/                 # GPL-3.0: transmitter noise (~0.1% span) + low-flow cutoff (realism; GRFICS already clamps), valve-feedback faults,
â”‚   â”‚                              # zero-position leak term, time scale; Dockerfile.derived, LICENSE, README listing every change
â”‚   â”œâ”€â”€ p2_gasline/
â”‚   â”‚   â”œâ”€â”€ SPEC.md                # gas, equipment, valves, sensors, OPC UA nodes, physics + analytic check (committed before code)
â”‚   â”‚   â”œâ”€â”€ plant_map.yaml  isolation_list.yaml  confirmed.yaml   # the plan = map + list (also the plan-check set's base)
â”‚   â”‚   â”œâ”€â”€ opcua_map.yaml  thresholds.yaml   # protocol: opcua; tags, spans, freshness; P2 thresholds (tuned on P2 tuning seeds)
â”‚   â”‚   â”œâ”€â”€ model.py               # physics (isothermal N2 volumes, gas valve law), pure
â”‚   â”‚   â”œâ”€â”€ server.py              # asyncua server at 192.168.95.50:4840; users zerostate (read) / operator (*.CMD); write-attempt log
â”‚   â”‚   â”œâ”€â”€ faults.py  truth.py    # via docker exec on a unix socket inside the container, never the network (eval only)
â”‚   â”‚   â”œâ”€â”€ Dockerfile
â”‚   â”‚   â””â”€â”€ validation/            # analytic blowdown comparison â†’ blowdown_overlay.svg (stdlib, no plot dependency); error % in eval/results/p2_validation_<date>.json
â”‚   â””â”€â”€ p3_wntr/                   # stretch
â”œâ”€â”€ eval/
â”‚   â”œâ”€â”€ scenarios/                 # P1 S0â€“S13 (S7 skip, S7-same same verifier, S13 reopen) as YAML (plant, fault, onset range, severity range, expected verdicts); p2/ for P2
â”‚   â”œâ”€â”€ tools/credits_report.py    # copies /data/credits.jsonl out of the container â†’ dated summary in D:\grfics\credits_log.md
â”‚   â”œâ”€â”€ tools/export_bundle.py     # episode â†’ bundle.json.gz v2 (docs/BUNDLE.md); --runs-dir for full signals kept elsewhere
â”‚   â”œâ”€â”€ tools/capture_frames.py    # frames set: operator sets random valve positions, frames + truth sidecars outside git
â”‚   â”œâ”€â”€ tools/timescale_test.py    # Phase 1: time-scale stability runs (Ã—1 / Ã—10 / Ã—5) â†’ results/timescale_<date>.json
â”‚   â”œâ”€â”€ tools/vent_fidelity.py     # Phase 1 rev 3: manual-mode vent at Ã—1 vs chosen scale vs physics â†’ results/vent_fidelity_<date>.json
â”‚   â”œâ”€â”€ tools/smoke_table.py       # Phase 1: smoke table from runs/<episode>/ â†’ results/smoke_p1_<date>.md
â”‚   â”œâ”€â”€ seal.py                    # one sealed batch: scoring seeds â‰¥ 10000 from os.urandom, shuffled; manifest + salt OUTSIDE the repo (D:\grfics\sealed\)
â”‚   â”œâ”€â”€ sealed_hash_<batch>.txt    # committed SHA-256(salt + manifest) per batch, before its first scoring episode, then tag bench-freeze-<batch>
â”‚   â”œâ”€â”€ claims.yaml                # claim id â†’ tests â†’ result key â†’ exact README sentence
â”‚   â”œâ”€â”€ runner.py                  # runs on the host (sim via localhost:80, operator via docker exec); one episode: check router+IDS rules, note eve.json byte offset â†’ plant up â†’ operator â†’ faults â†’ zerostate â†’ record â†’ re-check rules (missing = episode invalid); IDS alerts counted after the offset (file shrank = rotated â†’ from 0)
â”‚   â”œâ”€â”€ baselines/gauge_rule.py      # measured pressure < 150 kPa and every measured flow <= its meter cutoff (1 % of full scale) at the last step mark, else block; scored by score.py
â”‚   â”œâ”€â”€ baselines/muse_alone.py      # Muse Spark alone: plan + measured series from the bundle, one call per episode, temperature 0, pinned pass/block mapping; --dry-run projects calls and cost; ledgered by llm/client.py
â”‚   â”œâ”€â”€ baselines/muse_alone_v1.md   # its prompt, committed before the first live call
â”‚   â”œâ”€â”€ plan_cases/make_cases.py   # PC0â€“PC6 from the P2 map + list by mutation; labels written before the checks run
â”‚   â”œâ”€â”€ importer_set/              # 12 cases (6 texts, 6 rendered sheets) + gold lists, committed before any importer run: cases.yaml (gold), t01â€“t06.txt, s01â€“s06.png + s06.pdf, make_sheets.py
â”‚   â”œâ”€â”€ frames_set/                # hash list + label hash only (frames outside git)
â”‚   â”œâ”€â”€ voice_test.py              # 20 clips (outside git) â†’ transcript â†’ intent; expected intents committed; uses llm/client.transcribe (Muse Voice Transcribe) and the API's parse_intent
â”‚   â”œâ”€â”€ voice_expected.yaml          # the 20 clips' expected intents, committed before any clip is transcribed
â”‚   â”œâ”€â”€ run_benchmark.py           # loops runner.py over a sealed manifest: resumable, one retry, stops after 3 INVALID in a row, 05:00 watchdog
â”‚   â”œâ”€â”€ plan_benchmark.py  read_accuracy.py  p2_validation.py  importer_accuracy.py
â”‚   â”œâ”€â”€ score.py                   # opens seal, checks every episode (manifest, batch, plan hash, audit chain, replay), labels from truth under both hazard definitions (DECISIONS Nov 3), Wilson CIs -> results/score_<batch>.{json,md}
â”‚   â”œâ”€â”€ claims_audit.py            # reads claims.yaml: tests exist + pass, result keys exist, README sentence matches
â”‚   â””â”€â”€ results/                   # committed outputs (json + md) with commit hash: voice_runs.md (every voice run and its notes), timescale_<date>.json, smoke_p1_<date>.md, â€¦
â”‚       â”œâ”€â”€ bench/<batch>/<episode>/  # scoring episodes of a sealed batch (+ progress.jsonl, signals_sha256.json: hash of each full local signals.jsonl; seal/: the manifest and salt, published after scoring so anyone can check eval/sealed_hash_<batch>.txt); same files as episodes/; p1 S0, S4-small, S1b also carry bundle.json.gz (samples for `zs api --replay`, G9)
â”‚       â””â”€â”€ episodes/<episode>/    # per-episode audit_export, verdict, meta, ids, events, truth.jsonl.gz: anyone can replay and re-score
â”œâ”€â”€ tests/
â”‚   â”œâ”€â”€ test_readonly.py           # no plant-protocol write call anywhere; only adapters/ import pymodbus/asyncua; no write*/set* methods in adapters
â”‚   â”œâ”€â”€ test_firewall.py           # AST scan: src/zerostate imports nothing from plants/ or eval/, no GRFICS web URL
â”‚   â”œâ”€â”€ test_models.py             # no approval member; extra fields rejected; plan hash stable/changes; session edits don't touch plan hash
â”‚   â”œâ”€â”€ test_modbus_adapter.py     # in-process Modbus server: scaled values; server down â†’ BAD
â”‚   â”œâ”€â”€ test_opcua_adapter.py      # in-process P2 server: values, StatusCode quality, SourceTimestamp â†’ STALE, down â†’ BAD; zs picks the adapter by protocol
â”‚   â”œâ”€â”€ test_p2_server.py          # P2 server permission check: zerostate writes refused + logged, operator *.CMD only, timestamps advance
â”‚   â”œâ”€â”€ test_p2_model.py  test_p2_validation.py   # P2 physics (travel, limit switches, faults, noise, scenario keys); C12 < 2 %
â”‚   â”œâ”€â”€ test_freshness.py          # placeholder, STALE, constant_ok_raw, dead group (injectable clock)
â”‚   â”œâ”€â”€ test_plant_map.py          # map loads; every plan tag exists in the map
â”‚   â”œâ”€â”€ test_build.py              # merge deterministic, never invents a value; P2 plan passes every plan rule, P1 BLOCKED by SOFTWARE + TYPE; plan check at session start (refuse / override) and its replay
â”‚   â”œâ”€â”€ test_plan_cases.py         # plan-check set: generator deterministic; every PCn label matches the rules on one seed
â”‚   â”œâ”€â”€ test_modbus_scan.py        # scan script offset check
â”‚   â”œâ”€â”€ test_timescale_judge.py    # time-scale pass/fail criteria (eval/tools/timescale_test.py)
â”‚   â”œâ”€â”€ test_runner.py             # runner logic without the lab: seeded draws, router-rule order
â”‚   â”œâ”€â”€ test_published_replay.py   # C11 regression gate: every published P1 episode replays identically under today's rules
â”‚   â”œâ”€â”€ test_llm_client.py         # fake opener: box parsing, strict-JSON retry then fail, ledger, budget stop, key never logged
â”‚   â”œâ”€â”€ test_camera.py             # fake models + Pillow fixtures: region matching, unreadable, freeze, LIVE-CAMERA, optional/required, data-only track untouched, status, two-track replay
â”‚   â”œâ”€â”€ test_frame_service.py      # frame service pure parts: view allow-list, noise keeps size/format
â”‚   â”œâ”€â”€ test_bundle.py             # episode bundle: export â†’ load â†’ schema validates; key-like strings refused
â”‚   â”œâ”€â”€ test_score.py              # score.py on a fixture seal: both hazard definitions, windows, Wilson CIs, refused hash, INVALID entries, S1b note
â”‚   â”œâ”€â”€ test_baselines.py          # gauge rule on committed p1 episodes; Muse alone with a fake client only (one call, temperature 0, pinned mapping, unavailable listed, dry run calls nothing); both scored by score.py
â”‚   â”œâ”€â”€ test_api_contract.py       # API (docs/API.md): every endpoint returns its schema, error codes, audit opened read-only, steps/sign/start only add inbox rows, playwright-test refused on real /data, voice never reaches sign/verify/reopen; replay mode serves every published episode and refuses writes
â”‚   â”œâ”€â”€ test_bench.py              # seal hash, scoring refusals (manifest, tag, dirty tree), batch resume/retry/stop, watchdog
â”‚   â”œâ”€â”€ test_gate.py               # no approval member; FAIL beats UNKNOWN; monotonic; signature closes; stamping; no never-say words; camera only on the with-camera track
│   ├── test_wording.py            # never-say checker: list matches PROJECT.md; docs/*.md and src/ string literals clean
│   ├── test_claims_audit.py       # claims audit on a tmp claims.yaml + fake results (missing/failing test, key, README differs); real claims.yaml well formed
â”‚   â”œâ”€â”€ test_session.py            # warm-in, plan-hash refusal, pending, step order, verify, reopen, settle before monitoring, UNKNOWN grace, stop
â”‚   â”œâ”€â”€ test_operator.py           # operator: setpoints before coil, readback mismatch aborts, manual off restores defaults
â”‚   â”œâ”€â”€ conftest.py                # shared in-process Modbus server fixture (adapter + operator tests) + in-process P2 OPC UA server
â”‚   â”œâ”€â”€ test_audit_chain.py  test_replay.py  test_importer_gate.py
│   ├── test_plant_agnostic.py     # C2 (D4): AST scan, no plant id / tag / node id in src/zerostate literals or identifiers (xfail until P3-9 removes the cli/image_import defaults)
â”‚   â”œâ”€â”€ net/test_container_isolation.py   # run inside container: only PLC:502 reachable; truth, host ports, DMZ, router, internet not; app can't change net config
â”‚   â”œâ”€â”€ net/test_api_isolation.py  # run inside zs-api: only the proxy reachable (no plant, frames, internet); can't change the allowlist; audit volume read-only
â”‚   â”œâ”€â”€ checks/                    # test_<rule>.py per rule (test_paths.py â€¦ test_reset.py), a passing and a failing case each; test_timescale_invariance.py
â”‚   â”œâ”€â”€ live/                      # marker `live`, run from the host against the lab: test_patch.py, test_operator_net.py
â”‚   â”‚                              # tests/checks/synth.py: synthetic P1 windows (vent model, 4 Hz polls) for rule tests
â”‚   â”‚                              # tests/checks/plan_synth.py: small hand-built plant maps and plans for the plan-rule tests
â”‚   â”‚                              # tests/checks/synth_p2.py: P2 plan + windows sampled from plants/p2_gasline/model.py (4 Hz, x30)
â”‚   â”œâ”€â”€ ui/                        # marker `ui`: Playwright (headless Chromium) on the console, against tests/ui/fake_api.py (replay mode over the sample bundles + one faked in-progress session)
â”‚   â”‚                              # (real plan/draft routes + recorded bench sessions as SessionDetail) on a throwaway data dir
â”‚   â””â”€â”€ fixtures/                  # small recorded episodes for offline tests
â””â”€â”€ scripts/
    â””â”€â”€ modbus_scan.py             # Phase 0: map GRFICS registers (read-only)
```

## 3. Boundaries (enforced by tests, not by convention)
| Rule | Enforced by |
|---|---|
| `src/zerostate` never imports `plants/` or `eval/` | tests/test_firewall.py |
| No code in `src/zerostate` references GRFICS web API URL | tests/test_firewall.py |
| No write path in any adapter | tests/test_readonly.py |
| ZeroState container reaches only PLC:502, P2 OPC UA, the proxy (which tunnels only to api.meta.ai:443) and the frame service | tests/net/test_container_isolation.py |
| No Modbus write from ZeroState's IP; IDS proven to see writes | deploy/check_ids.ps1 (9100001 = 0, 9100002 > 0 per episode) |
| No plant-specific name (plant id, tag, node id) in `src/zerostate` | tests/test_plant_agnostic.py |
| Only `plants/*/truth.py` and `eval/` read ground truth | tests/test_firewall.py |
| Every check exports RULE_ID + RULE_VERSION and has a pass and a fail test | tests/checks/ + claims_audit |
| Every LLM call goes through `llm/client.py` and is logged with cost | tests/test_firewall.py (only llm/client.py names the Meta host) + claims_audit |
| The data-only verdict path imports no model or camera code | tests/test_firewall.py |
| Only a person confirms a plan | CLAUDE.md rule; confirmations carry name, role, date in confirmed.yaml and the audit log |
| No secret in repo | .gitignore + pre-commit secret scan |

## 4. Claim â†’ code â†’ proof map
| Claim | Code | Proof |
|---|---|---|
| C1 read-only, reaches only PLC Modbus | adapters/, deploy/ network rules | test_readonly, test_firewall, net/test_container_isolation, check_ids |
| C2 same engine, one commit, both plants; no plant name in src/ | plants/p1, p2 | test_plant_agnostic + run_benchmark (bench-freeze-2 and bench-freeze-p2 on one commit) |
| C3 plan errors | checks/plan/* | plan_benchmark |
| C4 instrument evidence | checks/live/alive, relation | test_alive, test_relation + S1/S2/S3 |
| C5/C6 misses, false blocks | gate + all checks | run_benchmark + score |
| C7 camera reading | camera/*, plants/frame_service | read_accuracy |
| C8 lying feedback | checks/live/relation, valve, camera | S8 |
| C9 stale data never passes | adapters/freshness, checks/live/quality | test_freshness, test_quality + S12 |
| C10 gate rules | models/verdict, gate, session (two tracks) | test_gate, test_firewall |
| C11 hash chain + replay | audit/* | test_audit_chain, test_replay |
| C12 P2 implementation check | plants/p2_gasline/model | p2_validation |
| C13 process rules | checks/process/* | test_sequence, test_independence, test_reset + S7 |
| C14 importer | importers/* | test_importer_gate, importer_accuracy |

## 5. Conventions
- Build workflow: this planning session writes one spec per phase in `docs/specs/PHASE_<n>.md` (what + acceptance tests + gate, never how). VS Code Claude Code with Ponytail plans â†’ codes â†’ tests from the spec. Rules for coding agents: `CLAUDE.md` at repo root (incl. the never-cut list).
- Python â‰¥3.11 in a repo venv: `python -m venv .venv`; `.venv\Scripts\Activate.ps1`; `pip install -e .[dev]` (Windows/PowerShell). Runtime in Docker with pinned deps.
- Git: one commit per spec item or smaller, never with failing tests; branch per phase named `p<n>-work` (never the same name as a tag); nothing is pushed to `main` directly, everything lands through a pull request; tag `phase-<n>` only after the gate passes and the PR is merged, then delete the work branch; gate output saved in `docs/specs/PHASE_<n>_GATE.md`. Pre-commit: ruff, detect-secrets, fast pytest.
- Formatting/lint: ruff; tests: pytest; types: pydantic models, mypy on src/ (best effort).
- Time: all timestamps UTC, ISO-8601; plant source timestamp kept separate from receive timestamp.
- IDs: rule ids exactly as in ARCHITECTURE (`PLAN-PATHS`, `LIVE-ALIVE`, `PROC-RESET` â€¦), version in the separate `RULE_VERSION` field; file name = lower-case suffix (`checks/live/alive.py`), test = `tests/checks/test_alive.py`; scenario ids as in EVAL.md; claim ids as in CLAIMS.md.
- Clocks: process thresholds in process-seconds (`*_process_s`, converted with the plant's `process_time_scale`); freshness windows in wall-clock seconds (`*_wall_s`).
- Versioning: package semver; each rule has its own version; thresholds YAML has a version; all three stamped on every verdict.
- Commit messages: `P<phase>-<item> <what> (<claim ids>)`.

## 6. Failure behaviour (product rules)
- Plant data stops / stale / bad quality â†’ affected findings UNKNOWN â†’ verdict ESCALATED, never pass.
- Model API down or over budget â†’ camera and explanations marked unavailable; gate still runs on data; verdict can't be NO_DISCREPANCY if the envelope requires camera evidence.
- Unconfirmed or edited envelope (hash mismatch) â†’ refuse to start.

## 7. What moves from D:\grfics into the repo
- `zerostate_test.py` â†’ reference only (kill test, Oct 27); not copied. Its lessons go to MODEL_NOTES.md.
- `log_plant.py` â†’ superseded by `adapters/` + `eval/runner.py`.
- `credits_log.md` stays canonical at D:\grfics; `llm/client.py` writes the container ledger `/data/credits.jsonl`, and `eval/tools/credits_report.py` appends a dated summary to `credits_log.md` after each live session.

## 8. Owner decisions needed
Operator page tech â€” plain HTML/JS served by FastAPI (suggested, fastest) vs React. (Everything else is decided: PROJECT.md decisions 1â€“20.)
