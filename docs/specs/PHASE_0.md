# Phase 0 — Foundations (spec)

Goal: a git repo where ZeroState runs as a container in the GRFICS DMZ, reads the PLC over Modbus **read-only**, turns raw registers into quality-tagged signals, and is **proven able to reach only the PLC's Modbus port**. No checks, no models, no internet yet.
Branch: `phase-0`. Due: Sat Oct 31 night. Gate at the bottom.

## Facts from GRFICS source and the running lab (don't rediscover; confirm live where marked)
- PLC 192.168.95.2:502 (OpenPLC, active program `326339.st`). Input registers %IW100–112 = f1_valve_pos, f1_flow, f2_valve_pos, f2_flow, purge_valve_pos, purge_flow, product_valve_pos, product_flow, pressure, level, a_in_purge, b_in_purge, c_in_purge (raw 0–65535). Holding %QW100–103 = valve commands. Coil %QX0.0 = manual_mode; %QW10–13 = manual setpoints. OpenPLC maps %IWn → input register n, %QWn → holding register n, %QXa.b → coil 8a+b. **Confirm addresses live (P0-6).**
- Scales: valve pos 0–100 %; flows full scale f1 1000, f2 500, purge 2000, product 500; pressure 0–3200 kPa; level 0–100 %; analyzer 0–1.
- Pressure/level/flows on Modbus are the *measured* (faultable) values; valve positions are the *true* positions.
- Remote I/O devices (.10–.15) serve placeholder values until the simulator connects, and keep last values if it dies. They are seeded `co=101…200`, `hr=201…300`, `ir=301…400` (`/app/modbus/modbusdevice.py`), so placeholders are raw **values**. GRFICS clamps every value to 0–65535 (`clamp_value`), so noise can't wrap around. The PLC mirrors whatever it last polled; what it shows before the sim connects is recorded by P0-6.
- GRFICS runs pymodbus 3.9.2; we pin the same.
- Networks: b-ics-net 192.168.95.0/24 and c-dmz-net 192.168.90.0/24 (macvlan on separate parents, so cross-zone traffic must transit the router); router 192.168.95.200 / 192.168.90.200. DMZ containers add `ip route add 192.168.95.0/24 via 192.168.90.200` (needs NET_ADMIN), like the HMI.
- Used DMZ addresses: HMI .107, kali .6, wazuh .20, zeek .30, caldera .250, router .200. ZeroState takes **.60**; the operator container (Phase 1) takes **.70**.
- **Router FORWARD chain today** (read Oct 31): policy DROP; `ACCEPT RELATED,ESTABLISHED`; `DROP INVALID`; **`ACCEPT` all**; … Our rules must sit above the allow-all. Rules are not persistent: router restarts or a rule apply in its web UI wipe them.
- **Same-subnet traffic never reaches the router.** .60 → other DMZ hosts (.107 HMI web, .250 Caldera, …) and .60 → the router's own services go direct / to INPUT, not FORWARD. Router rules alone can't enforce "PLC Modbus only".
- **Windows-published ports**: simulation :80 (truth `/data/index.php`), PLC web :8080 (OpenPLC, can upload programs), EWS :6080, HMI :6081, kali :6088, caldera :8888, router :51820/udp. A container on any Docker bridge network can usually reach these through `host.docker.internal` → ZeroState joins **no** bridge network.
- Truth endpoints on the ICS net: 192.168.95.45:80 (`/data/index.php`) and :55555 (simulator JSON socket). The a-grfics-admin bridge reaches the simulator directly → ZeroState must NOT join it.
- Router Suricata 7.0.10 loads `/etc/suricata/rules/*.rules`, Modbus app-layer enabled on port 502 (confirmed Oct 31), runs under supervisord (program `suricata`), IDS-only (af-packet), logs `/var/log/suricata/eve.json`.

## Items (one commit each, or smaller)
### P0-1 Repo init
- `git init` in `D:\grfics\zerostate`; first commit on main = docs + CLAUDE.md (`P0-0 docs baseline`); then branch `phase-0`.
- `.gitignore` (.venv, .env, __pycache__, *.sqlite, runs/, frames/, eval/sealed/), `.gitattributes` (`*.sh text eol=lf`), `.dockerignore`. LICENSE Apache-2.0. `pyproject.toml`: python ≥3.11; deps `pydantic>=2`, `pyyaml`, `pymodbus>=3.6,<3.10`; dev `pytest`, `ruff`, `pre-commit`, `detect-secrets`. Pytest config: marker `net`, `addopts = -m "not net"`. Pre-commit: ruff, detect-secrets (`.secrets.baseline`), fast pytest. Venv: `py -3.13 -m venv .venv` (never conda base).
- Accept: `pre-commit run --all-files` passes.

### P0-2 Data models (`src/zerostate/models/`)
- `verdict.py`: `Verdict` = BLOCKED | ESCALATED | NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF. `FindingStatus` = PASS | FAIL | UNKNOWN.
- `signal.py`: `Quality` = GOOD | STALE | UNKNOWN | BAD. `Signal{tag, value: float|None, raw: int|None, quality, source_ts: datetime|None, recv_ts: datetime}`.
- `evidence.py`: `Finding{rule_id, rule_version, status, message, refs: list[str]}`.
- `envelope.py`: `IsolationPlan` and its parts as in ARCHITECTURE §2 (fields exactly as named there). Pydantic `extra="forbid"`. `IsolationPlan.content_hash()` = SHA-256 of canonical JSON. Plan models are frozen and use tuples for collections (a frozen model holding a list can still be mutated in place). `SessionState` (statuses, signatures, timestamps) is a separate model that holds `plan_hash`; nothing in it feeds the plan hash.
- Tests (`tests/test_models.py`): enum has no member containing "SAFE"; unknown field rejected; plan hash stable across load/dump and changes when any plan field changes; adding a signature / changing a status in SessionState leaves the plan hash unchanged; `plants/p1_grfics/envelope.yaml` stub loads (a minimal plan is enough in P0).
- Claims: C10 (partial).

### P0-3 Read-only adapter (`src/zerostate/adapters/base.py`, `modbus.py`)
- `ReadOnlyAdapter` protocol: `read(tags) -> dict[str, Signal]`. (subscribe/history: later phases.)
- `ModbusReadOnly(map_path)`: loads a map file (schema in P0-5), groups contiguous registers per host/table, uses only read_coils / read_discrete_inputs / read_holding_registers / read_input_registers, scales raw → engineering units. Connection, exception or short response → every affected tag `quality=BAD`, value None. Unknown tag → `KeyError`. Modbus has no source timestamp → `source_ts=None`. `retries=1`.
- Tests:
  - `tests/test_readonly.py` (AST scan of `src/zerostate/**`):
    - no call to a plant-protocol write: any attribute starting with `write_` (write_coil(s), write_register(s)), `mask_write_register`, `readwrite_registers`, asyncua `write_value` / `set_value` / `write_attribute`, and raw `execute` / `send` (which could carry a write request); no import of pymodbus write-request classes. Ordinary file writes (`f.write`) are allowed. A self-test proves the scanner flags a planted bad snippet.
    - only modules under `src/zerostate/adapters/` import `pymodbus` or `asyncua`.
    - no class in `adapters/` defines a method starting with `write` or `set`.
  - `tests/test_modbus_adapter.py`: in-process pymodbus TCP server on localhost with known registers → correct scaled values; server stopped → BAD.
- Claims: C1.

### P0-4 Freshness (`src/zerostate/adapters/freshness.py`)
- `FreshnessTracker` per tag: map file gives `placeholder_raw` (raw **values**, not addresses), `max_static_wall_s` (wall-clock seconds) and `constant_ok_raw` (`any` or a list of raw values). Raw in placeholder set → UNKNOWN. Value unchanged longer than `max_static_wall_s` → STALE, unless the current raw value is allowed to be constant (`any`, or in the list): then GOOD, and `static_for_s(tag)` exposes how long. P1: `any` for valve positions (Phase 1: `[0, 65535]` once the patch adds noisy feedback), commands, setpoints, manual_mode; `[0]` for flows (low-flow cutoff); `[]` for pressure, level, analyzer. A tag is noise-carrying while it is not at an allowed-constant value. Group rule: a `source_group` is dead (all its tags STALE) when it has ≥ 1 noise-carrying tag and all of them are static beyond their window. Known limit: a device with its valve closed and flow 0 has no noise-carrying tag, so its own liveness can't be judged; the always-noisy tank pressure carries PLC-path liveness.
- Design basis: healthy measured values carry transmitter noise (added by the Phase 1 patch), so a live reading changes on every poll and "stopped changing" means a broken path anywhere along sim → I/O → PLC → network. Until the patch lands, the live plant is noise-free, so P0 only proves the logic offline.
- Tests (`tests/test_freshness.py`): placeholder → UNKNOWN; change resets timer; noisy tag static beyond window → STALE; `any` tag stays GOOD with static_for_s; flow frozen at non-zero → STALE; flow at 0 → GOOD; all noise-carrying tags in a group static → whole group STALE; group with no noise-carrying tag → not dead; BAD passes through. Use an injectable clock (no sleeps).
- Claims: C9 (partial).

### P0-5 P1 register map (`plants/p1_grfics/modbus_map.yaml`)
- Top level: `process_time_scale` (1 for stock GRFICS; the patch sets it in Phase 1).
- One entry per tag: `tag, host, port, table (ir|hr|coil|di), address, scale_min, scale_max, unit, source_group, placeholder_raw, max_static_wall_s, constant_ok_raw, confirmed`. Tags from the facts above (13 IR + 4 commands + manual_mode + 4 manual setpoints). ZeroState reads the command / manual-mode registers; it never writes them.
- Addresses start as source-derived values with `confirmed: false`; P0-6 flips to true. `placeholder_raw` starts empty; P0-6 fills it.
- Test (`tests/test_plant_map.py`): map loads; every tag in the envelope stub exists in the map.

### P0-6 Live scan (`scripts/modbus_scan.py`)
- Read-only. Reads PLC IR 95–115, HR 0–15 and 95–106, coils 0–8; flags the offset by checking pressure decodes to 2000–3000 kPa and level to 20–80 % in normal running. `--seconds N` repeats the read once per second; `--out PATH` writes every sample (raw + scaled) as JSON; human summary goes to stderr.
- Run inside the zerostate container (P0-7); the host pulls the JSON out with `docker cp` (no PowerShell `>` redirect: encoding) into `plants/p1_grfics/scan_<date>.json`. Update the map (`confirmed: true`) from it.
- Placeholder capture: start `docker exec zerostate python scripts/modbus_scan.py --seconds 90 --out /tmp/scan_restart.json` **first**, then a person runs `docker compose restart simulation` from `D:\grfics`. Whatever the PLC shows before the sim reconnects becomes `placeholder_raw`. (ZeroState never gets Docker access; the restart is done by the person.)

### P0-7 Deploy (`deploy/`)
Two containers, so the isolation is a control, not a procedure: even root inside `zerostate` can't change it.
- `Dockerfile.net` + `net_setup.sh` → helper container **`zerostate-net`** (alpine, pinned tag; iptables, ip6tables, iproute2). `net_setup.sh` (`set -eu`, fail closed: any error exits, so `zerostate` never starts):
  1. `ip route add 192.168.95.0/24 via 192.168.90.200`
  2. OUTPUT **allowlist**: allow `lo`; allow RELATED,ESTABLISHED; allow tcp to 192.168.95.2:502 (later: the egress proxy on the internal network); then policy DROP. This is what stops same-subnet and router-INPUT traffic.
  3. IPv6: compose sets `net.ipv6.conf.all.disable_ipv6=1`; if IPv6 is still present, ip6tables allow `lo`, OUTPUT policy DROP.
  4. `exec sleep infinity`. Healthcheck: OUTPUT policy is DROP and the PLC rule exists (`iptables -C`).
- `Dockerfile` → product container **`zerostate`**: python:3.13-slim (same Python as the venv); iproute2 + iptables installed only so the "can't change rules" test is meaningful; default `USER zs`; copies `src scripts tests` and only `plants/p1_grfics/modbus_map.yaml` + `envelope.yaml` (→ `/app/config/p1_grfics/`), never truth/fault code; exact pinned deps (pymodbus==3.9.2); no entrypoint script.
- `docker-compose.zerostate.yml` (override, used with Fortiphyd's file from `D:\grfics`):
  - `zerostate-net`: `cap_add: NET_ADMIN`, network `c-dmz-net` only (ipv4 192.168.90.60), IPv6 sysctl. **No bridge / internet network; not on a-grfics-admin; no dns entry.**
  - `zerostate`: `network_mode: "service:zerostate-net"`, `cap_drop: [ALL]`, `depends_on: zerostate-net (service_healthy)`. If `zerostate-net` restarts, restart `zerostate` too (it keeps the old namespace).
  - Root inside `zerostate-net` (which has NET_ADMIN) is infrastructure, like the host; it is documented, not claimed against.
- `apply_router_rules.ps1` (idempotent; re-run after any router restart or rule apply in the router UI; prints the FORWARD chain and fails if our rules are not above the allow-all):
  - `docker exec router iptables -I FORWARD 1 -s 192.168.90.60 -d 192.168.95.2 -p tcp --dport 502 -j ACCEPT`
  - `docker exec router iptables -I FORWARD 2 -s 192.168.90.60 -j DROP`
  - copy `deploy/suricata_zerostate.rules` → router `/etc/suricata/rules/zerostate.rules`, then `docker exec router supervisorctl restart suricata`; check it is RUNNING and that `suricata.log` reports no error on our sids.
  - The net tests can't prove the router layer (the container filter would block anyway), so the router layer is checked by presence: this script now, the episode runner from Phase 1.
  - (.70 operator rules are added in Phase 1.)
- `suricata_zerostate.rules` (same rule twice):
  - `alert modbus 192.168.90.60 any -> any 502 (msg:"ZeroState Modbus write"; modbus: access write; sid:9100001; rev:1;)`
  - `alert modbus 192.168.90.70 any -> any 502 (msg:"Operator Modbus write"; modbus: access write; sid:9100002; rev:1;)` — positive control: from Phase 1, every episode must show 9100002 > 0, proving rule syntax and IDS visibility.
- `check_ids.ps1`: counts sid 9100001 and 9100002 in router eve.json; prints both; non-zero exit if 9100001 > 0. (`-RequireOperator` switch, used from Phase 1: also fail if 9100002 == 0.) Phase 0 can only show 9100001 = 0; the positive control needs the operator container, so C1 stays NOT BUILT until Phase 1.

### P0-8 Firewall tests
- `tests/test_firewall.py` (fast): AST — `src/zerostate` imports nothing from `plants` or `eval`; no string literal in `src/zerostate` contains `index.php` or `55555`; no int literal 55555.
- `tests/net/test_container_isolation.py` (marker `net`, runs inside `zerostate` **as root**, the worst case):
  - TCP connect to 192.168.95.2:502 succeeds; adapter read of `pressure` returns GOOD with 0 < value < 3200.
  - Each of these fails within 2 s: 192.168.95.45:80, 192.168.95.45:55555, 192.168.95.10:502, 192.168.95.2:8080, `host.docker.internal`:80 and :8080 (and fails to resolve is a pass), 192.168.90.107:8080 (HMI, same subnet), 192.168.90.200:80 (router itself), 1.1.1.1:443 (internet).
  - IPv6 disabled, or ip6tables OUTPUT policy DROP.
  - As root: `iptables -A`, `ip6tables -A` and `ip route add` each fail with a permission error (binaries present, so it isn't a "not found" pass); `CapEff` is 0 in `/proc/self/status`.
- Claims: C1.

## Not in Phase 0
Checks, gate, audit log, episode recorder, operator container, GRFICS patch (noise, valve feedback, leak, time scale), camera, models, egress proxy, operator page (all Phase 1+).

## Gate (paste outputs into docs/specs/PHASE_0_GATE.md)
From `D:\grfics` in PowerShell, GRFICS running:
1. `docker compose -f docker-compose.yml -f zerostate\deploy\docker-compose.zerostate.yml up -d --build zerostate` (starts `zerostate-net` first)
2. `.\zerostate\deploy\apply_router_rules.ps1` → prints chain, our two rules above the allow-all
3. `docker exec zerostate python scripts/modbus_scan.py --seconds 10 --out /tmp/scan_run.json` → pressure ≈ 2700 kPa, level ≈ 44 % (matches the 3D view); placeholder capture done and map updated
4. `docker exec -u 0 zerostate pytest -m net -q` → all pass (root on purpose)
5. In the repo venv: `pytest -q` → all pass
6. `.\zerostate\deploy\check_ids.ps1` → 9100001 = 0
7. `/ponytail-review branch` findings addressed
Pass = all seven. Then merge, tag `phase-0`.

## Risks to watch
- pymodbus client API changed `slave=` → `device_id=` in 3.10; pinned <3.10.
- macvlan + Docker Desktop: GRFICS already runs on it; if the new container can't attach, report before working around it.
- Router rule order: the allow-all rule must stay below ours; `apply_router_rules.ps1` checks order and prints the FORWARD chain.
- iptables in `zerostate-net` on Docker Desktop: if the kernel module / nft backend is missing, setup exits and `zerostate` never starts; report before working around it (fallback is the router rule alone, and C1 wording must then shrink to "outside the DMZ").
- `network_mode: service:` with macvlan and a healthcheck-gated `depends_on`: if Docker Desktop misbehaves, report.
