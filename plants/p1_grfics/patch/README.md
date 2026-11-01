# GRFICS patch p1-1 (GPL-3.0)

A derived image of `fortiphyd/grfics-simulation` for ZeroState's live tests. These files are a
modification of GRFICSv3 (Fortiphyd, GPL-3.0) and stay under GPL-3.0 (`LICENSE`); the rest of the
ZeroState repository is Apache-2.0. Fortiphyd's compose file and web files are not modified.

## Source and image match
- Patched source: GRFICSv3 commit `8d611b773fa74e3a82ff149c447cff8380eaa99a`, cloned outside this
  repo at `D:\grfics\vendor\grficsv3` (LFS files skipped; not needed).
- Base image: `fortiphyd/grfics-simulation@sha256:ed3517811da2c4a542bf28b5f19f939ade8aa4d7ab1ac2de63c16087b34dd756`,
  label `org.opencontainers.image.revision = v1.3.3-2-g8d611b7` (same commit).
- Checked 2026-11-01: the image's `/app/modbus/*.py`, `run_all.sh` and `/var/www/html/data/index.php`
  are identical to the clone (line endings aside).

## Changes (exactly these)
| | Change | Where |
|---|---|---|
| A | `state.zs_patch_version = "p1-1"` (also `state.zs_time_scale`, `state.zs_noise`). Truth side only; Modbus devices never serve it. | `TE_process.cc` |
| B | `time_scale` from env `ZS_TIME_SCALE` (default 1.0, ≤ 0 → 1.0), read before `sampling_delay`; printed at start. | `TE_process.cc` |
| ~~C~~ | ~~Seeded noise~~ — not implemented (Phase 1 rev 3): noise is drawn per wall-clock tick, so a seed can't reproduce an episode. | — |
| D | Env `ZS_NOISE` (default 1): uniform ±0.1 % of span on measured pressure (3200), level (100), f1/f2/purge/product flow (1000/500/2000/500) and analyzer A/B/C (1); applied in healthy mode, on drift and in the non-dropped phase of dropout; never in frozen or the existing noise fault mode. Flows below 1 % of span read 0 (low-flow cutoff). Measured values clamped to their physical range (flows ≥ 0 and ≤ span, level 0–100, pressure 0–3200, analyzer 0–1), except in frozen mode, which holds. | `TE_process.cc` |
| E | `measured.<v>_valve_pos` for f1, f2, purge, product: true position ± 0.1 %, clamped 0–100. New inputs `<v>_pos_fault_mode` (0 none, 1 frozen, 2 offset +severity %, 3 fixed value = severity %) and `<v>_pos_fault_severity`; truth `state.<v>_pos_fault_*`. | `TE_process.cc/.h` |
| F | New input `<v>_leak_pct` (0–100): flow uses `max(true_pos, leak_pct)` as the opening, including the product "opening ≤ 0 → no flow" line. True position and feedback unchanged. Truth `state.<v>_leak_pct`. | `TE_process.cc/.h` |
| G | Remote I/O IR1 on the four valve devices serves `measured.<v>_valve_pos` instead of the true position. | `remote_io/modbus/{feed1,feed2,purge,product}.py` |
| H | `index.php` reads simulator replies with `fgets($fp, 65536)` (was 1500). The stock state JSON is already 1,473–1,477 bytes, so G's four feedback fields alone pushed it over and cut off every truth read and the web/3D view. Two lines plus a comment; approved Nov 1 as a deviation from "web files unchanged". (`fgets(…, 4096)` reads elsewhere are left; the patched JSON is ~1,950 bytes.) | `web_visualization/data/index.php` (`web.patch`) |

Unchanged: e-stop, all existing faults, the noise-floor scheduler, the PLC, and every web file except the two read sizes in H.
Known upstream quirk left as is: the analyzer's sampling-delay copy loop never runs, so the measured
analyzer tracks the live composition.

## Build
`.\build.ps1` (PowerShell): checks the clone is at the commit above, copies the simulation sources to
`%TEMP%\zs-grfics-build`, normalises them to LF, applies `TE_process.patch`, `remote_io.patch` and `web.patch`
(checks they applied), and builds `zerostate/grfics-simulation:p1-1` from `Dockerfile.derived`
(stage 1: GRFICS's own build base digest; stage 2: the pulled image above).
`deploy/docker-compose.zerostate.yml` runs it as `simulation` (`pull_policy: never`, no build context).
