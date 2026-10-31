# Phase 0 — gate output

Run 2026-10-31 ~21:30 UTC from `D:\grfics` in PowerShell, GRFICS running, branch `phase-0` at the review-fix commit.

| # | Gate item | Result |
|---|---|---|
| 1 | containers up (`zerostate-net` healthy first, then `zerostate`) | PASS |
| 2 | `apply_router_rules.ps1`: our allow/drop pair above the allow-all; Suricata 409 loaded / 33 failed (was 407 / 33) | PASS |
| 3 | scan: offset 0, pressure ≈ 2700 kPa, level ≈ 44 %; placeholder capture done (`plants/p1_grfics/scan_2026-10-31.json`), map updated | PASS |
| 4 | `pytest -m net` as **root** inside `zerostate`: 15/15 | PASS |
| 5 | `pytest -q` in the repo venv: 22 passed | PASS |
| 6 | `check_ids.ps1`: sid 9100001 = 0 | PASS |
| 7 | `/ponytail-review branch`: 1 must-fix (fresh tracker read frozen data as GOOD for 10 s), 1 nice-to-have (`read([])` returned all tags) — both fixed in `P0-4 review fix`, gate 1–6 re-run after | PASS |

Notes (stated, not hidden):
- 9100002 (operator positive control) is 0 because the operator container arrives in Phase 1; C1 stays NOT BUILT until it fires every episode.
- Live scan of a simulator restart: the PLC served identical last values with successful reads for ~50 s, then one sample of placeholder valve positions (raw 203). Replaying it through the tracker: pressure/level STALE 10 s into the freeze; placeholders UNKNOWN.
- Stock GRFICS is noise-free: analyzer and f1_flow sit still in normal running and go STALE. Expected until the Phase 1 noise patch.
- Known limit seen live: groups with valve closed and flow 0 (purge, feed2) have no noise-carrying tag and stayed GOOD during the freeze.
- Not checked: whether the router rotates `eve.json` (123 MB, growing); the Phase 1 runner should count IDS alerts per episode.

## Raw output (second run, after the review fix)
```
### 1. compose up
 Container zerostate-net Starting 
 Container zerostate-net Started 
 Container zerostate-net Waiting 
 Container zerostate-net Healthy 
 Container zerostate Starting 
 Container zerostate Started 
zerostate  Up Less than a second
zerostate-net  Up 5 seconds (healthy)
### 2. apply_router_rules.ps1
-P FORWARD DROP
-A FORWARD -s 192.168.90.60/32 -d 192.168.95.2/32 -p tcp -m tcp --dport 502 -j ACCEPT
-A FORWARD -s 192.168.90.60/32 -j DROP
-A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
-A FORWARD -m conntrack --ctstate INVALID -j DROP
-A FORWARD -j ACCEPT
-A FORWARD -s 192.168.95.0/24 -j ACCEPT
-A FORWARD -j LOGDROP
[30133 - Suricata-Main] 2026-10-31 21:29:43 Info: detect: 26 rule files processed. 409 rules successfully loaded, 33 rules failed, 0
Router rules and IDS rules in place.
exit=0
### 3. modbus_scan.py --seconds 5
2026-10-31T21:29:48.135374+00:00 pressure_raw=55322 level_raw=28912
2026-10-31T21:29:49.133968+00:00 pressure_raw=55251 level_raw=28910
2026-10-31T21:29:50.133999+00:00 pressure_raw=55208 level_raw=28907
2026-10-31T21:29:51.134432+00:00 pressure_raw=55280 level_raw=28902
2026-10-31T21:29:52.134679+00:00 pressure_raw=55331 level_raw=28898
offset check (shift -> plausible pressure+level): {-1: False, 0: True, 1: False}
exit=0
### 4. pytest -m net (as root in zerostate)
tests/net/test_container_isolation.py::test_plc_modbus_reachable_and_readable PASSED [  6%]
tests/net/test_container_isolation.py::test_everything_else_unreachable[192.168.95.45-80] PASSED [ 13%]
tests/net/test_container_isolation.py::test_everything_else_unreachable[192.168.95.45-55555] PASSED [ 20%]
tests/net/test_container_isolation.py::test_everything_else_unreachable[192.168.95.10-502] PASSED [ 26%]
tests/net/test_container_isolation.py::test_everything_else_unreachable[192.168.95.2-8080] PASSED [ 33%]
tests/net/test_container_isolation.py::test_everything_else_unreachable[host.docker.internal-80] PASSED [ 40%]
tests/net/test_container_isolation.py::test_everything_else_unreachable[host.docker.internal-8080] PASSED [ 46%]
tests/net/test_container_isolation.py::test_everything_else_unreachable[192.168.90.107-8080] PASSED [ 53%]
tests/net/test_container_isolation.py::test_everything_else_unreachable[192.168.90.200-80] PASSED [ 60%]
tests/net/test_container_isolation.py::test_everything_else_unreachable[1.1.1.1-443] PASSED [ 66%]
tests/net/test_container_isolation.py::test_ipv6_off_or_dropped PASSED   [ 73%]
tests/net/test_container_isolation.py::test_cannot_change_network[cmd0] PASSED [ 80%]
tests/net/test_container_isolation.py::test_cannot_change_network[cmd1] PASSED [ 86%]
tests/net/test_container_isolation.py::test_cannot_change_network[cmd2] PASSED [ 93%]
tests/net/test_container_isolation.py::test_no_effective_capabilities PASSED [100%]
============================= 15 passed in 19.40s ==============================
### 5. pytest -q (repo venv)
22 passed, 15 deselected in 1.51s
### 6. check_ids.ps1
9100001 (ZeroState writes): 0
9100002 (operator writes):  0
exit=0
```
