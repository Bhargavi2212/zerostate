# ZeroState — project brief

Status: design approved Oct 31 2026; revised the same day after an independent review (20 findings, all addressed — see DECISIONS.md), and again after a doc-alignment review against the running lab (decisions 13–20). All decisions approved. Nothing is built. Nothing is a claim until it is in CLAIMS.md with a passing test.

## One sentence
ZeroState is an independent, read-only second check on energy isolation: before a person opens equipment, it looks for mismatches between the isolation plan, the plant, and the evidence — and blocks out loud when it finds one or can't tell.

## Built as a product, not a demo
Standing rule: it must work for any plant and any isolation, and be tested on more than one plant. Plant-specific facts live in data (isolation envelope, plant map, physics relations), never in code. Every design choice is checked against real industry practice before it goes into a spec.

## The problem
Isolation kills people in two ways:
1. **The plan or the point is wrong** — LyondellBasell 2021 (chosen isolation valve was itself pressurised, 2 killed), Williams Geismar 2013 (boxed-in vessel without relief, 2 killed), Pemex Deer Park 2024 (wrong flange ~5 ft from the isolated one, 2 killed), Formosa Illiopolis 2004 (wrong reactor), HSG253 case (pump isolated only in software).
2. **The proof is wrong** — BP Amoco Augusta 2001 (plugged gauge read zero, 3 killed), Tosco Avon 1999 (passing valves, clogged drains, 4 killed), Giant Ciniza 2004 (valve open while believed closed), Milford Haven 1994 (display showed a failed-closed valve as open).
Scale: LOTO is OSHA's #4 most-cited standard (FY2025, 2,177 citations); in a 100-incident study, 45% of maintenance-phase immediate causes were permit/isolation failures (AIChE GCPS 2022). In process plants, line opening is also governed by OSHA 1910.119(f)(4) (PSM safe work practices).
Today's tools: permit/LOTO software records what was *declared*; camera AI checks PPE or that a lock is present; DCS copilots watch normal operation. We found no system that checks a declared isolation against live plant evidence (broad search, not proof — RESEARCH.md).

## What ZeroState does
Three layers of deterministic code; Meta models read, extract and explain, never decide a pass.
1. **Plan check** — every path from every energy source to the work is closed by an isolation point; no isolation device on the live side of the boundary; no boxed-in volume with a heat source and no relief; no control-system-only isolation (OSHA 1910.147(b)); isolation type fits the hazard (HSG253: positive / proved / non-proved isolation); every proved isolation has a proving point and its bleed isn't tied into a pressurised header; tags exist and witnesses sit on the right side of the boundary.
2. **Live evidence check** — each instrument is checked before it is trusted and again after the proof where a known disturbance makes that possible (alive, fresh, agrees with physics/redundancy, on the correct side); upstream pressure present so a hold test means something; hold test met criteria fixed before the run; valve command vs feedback; stale or frozen data never passes.
3. **Process check** — steps in order, stop at the first failure; installer ≠ verifier ≠ prover; temporary de-isolation resets verification; missing evidence = not verified.
Outputs only: `BLOCKED` (with reasons), `ESCALATED`, `NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF`. Never "safe". A human signs; the human try / test / bleed steps are unchanged.

## Design lineage
The only standards-accepted automated isolation verifier is the electrical absence-of-voltage tester (NFPA 70E 120.6(7) in the 2021/2024 editions, 120.5(7) in 2018; listed to UL 1436). ZeroState **borrows its structure** — same steps as the human method, check the instrument before and after, prove the connection to the right point, fixed sequence that stops at the first failure, one positive state — but it is **not equivalent**: an AVT actively tests itself on a known source and is SIL-3 listed; ZeroState is read-only, can only observe disturbances that happen, and has no rating.

## Positioning — the single "never say" list (all docs refer here)
Say: "an independent second check that can only raise objections, never approve"; "complements, not replaces, competent judgement" (HSG253 ¶115); "read-only; humans own safety decisions" (CISA/ACSC AI-in-OT principles, 2025); "tested on <named plants>".
Never say: verifies isolation; proves / certifies zero energy; makes LOTO safe; safety-rated; any SIL/PL/IPL credit; IEC 61508/61511, OSHA or "EU AI Act" compliant; equivalent to an AVT; reduces checks or headcount; would have prevented a named incident; 0% misses / never misses; "works for any plant" without naming tested plants; "never sees ground truth" while the camera renders the sim.

## Who uses it
Permit issuer / isolation authority (plan check); authorised person applying and proving the isolation (live check); receiver signing on.

## Plants we test on
- **P1 GRFICSv3** (Fortiphyd, GPL-3.0) — **live-evidence testbed.** It has only four PLC-driven control valves: no block valves, bleeds or proving points. So on P1 the plan check is *expected* to block (control-valve-only, unproved isolation) — that is a correct result we show. Live episodes run with an envelope that declares "assumed positive isolation upstream, out of scope", stated in every result. Read over Modbus.
- **P2 gas line (ours)** — **plan + live testbed** with block valves, double block and bleed, bleed/vent proving points, a heater (for the boxed-in check), redundant pressure transmitters. Read over OPC UA. Spec in plants/p2_gasline/SPEC.md (due Nov 1 night, or P2 is cut — see Phases).
- **Plan-check set** — envelopes with real-incident errors planted (EVAL.md), built on P2's plant map.
- Stretch: P3 water network (EPA/Sandia WNTR); CybICS.

## Camera
On P1 the 3D view is rendered from the simulator's true state, so the camera is an **idealised independent channel** (a perfect field observer). It stays in the product and the demo, but results with the camera are reported separately and labelled "idealised"; the headline numbers are data-only. Frames get added noise, lag and occlusion before use.

## In scope (must, by Nov 4)
Envelope schema; read-only adapters (Modbus, OPC UA); plan checks; live checks incl. stale-data and instrument checks; process checks; gate; hash-chained audit log; minimal operator page; camera reading via SAM 3.1 + Muse Spark; Muse Spark explanations; **Muse Spark importer** (isolation sheet image/PDF → draft envelope, human confirms); pre-registered benchmark on P1 (+ P2 if go).
## Should (if on time, in this order)
P2 plant (go/no-go Nov 1 night); Ed25519 signing; 3-read camera voting; richer operator screen.
## Out of scope
Real plants, certification; generating isolation plans; writing to any plant system; physical locks/keys, vent observation, spade fitting, field identification; watching people.
## Stretch
P3 water network; DEXPI import (pyDEXPI is AGPL); replay spoof via Modbus relay (S9); voice; offline model; glasses.

## Decisions
Approved Oct 31:
1. Patch GRFICS: measured valve-position feedback with faults, and a passing-valve leak term at zero position (separate labelled file, derived image, GPL-3.0).
2. Hold window: one fixed value per plant, set before sealing (P1 90 process-seconds, stated as compressed; real ≥ 10 min, PetroSA).
3. ZeroState is read-only; only `plants/*/operator.py` and `faults.py` write, and they live outside the product.
Revised (replaces the earlier "stop the PLC / e-stop" decision — the review showed stopping the PLC breaks scenario S6 and e-stop forces purge/product fully open, so no hold test is possible):
4. **Manual mode = the PLC's own manual mode** (coil %QX0.0, manual setpoints %QW10–13 in the active program 326339.st), driven by the operator script. S6 runs with the PLC in AUTO. E-stop is not used in episodes.
Approved Oct 31, 16:01 (Bhargavi delegated: "choose what's best to win"):
5. P1 = live-evidence testbed with the declared upstream assumption; its real plan is shown being BLOCKED (correct behaviour).
6. Camera kept in product and demo; P1 camera results labelled "idealised", headline numbers are data-only.
7. P2 go/no-go Nov 1 night; if no spec, submit P1 + plan-check set and say "tested on one live plant".
8. GRFICS time ×10 (stated as compressed); 5 episodes per scenario + 15 clean per plant; benchmark overnight Nov 2. Fallback (decision 19): if ×10 destabilises the PLC loops, ×5; if still unstable, real time with 3 episodes per scenario + 10 clean.
9. **Muse Spark importer is a MUST** (Meta tooling is 25% of the score, and "photo of an isolation sheet → blocked plan" is the strongest demo moment). To keep scope safe, Ed25519 signing and 3-read voting stay "should".
10. No practitioner reviewer line unless Bhargavi finds one; not mentioned otherwise.
11. ZeroState reads P1 from the DMZ through the GRFICS router (like the HMI does). The router can't filter Modbus by function code (its Suricata is IDS-only), so the read-only evidence is: no write code path + a Suricata alert rule for any Modbus write from ZeroState's IP + a test that the alert count is zero across all episodes. The same rule for the operator container's IP must fire every episode (positive control, decision 15).
12. Licence: Apache-2.0 for our code; GRFICS patch stays GPL-3.0 in its own folder.
Approved Oct 31 (doc-alignment review against the running lab):
13. **Freshness from transmitter noise, not a heartbeat.** The patch adds ~0.1% of span noise to measured pressure, level, flows and analyzer (≈65 counts at Modbus resolution), so a healthy reading changes every poll and "stopped changing" means a break anywhere in sim → I/O → PLC → network. No PLC program change, no read path to remote I/O. Practice basis: loss-of-process-noise diagnostics in pressure transmitters (plugged impulse line detection). Honesty cost: freeze detection on our plants depends on our noise model; stated in results.
14. **ZeroState never gets internet.** Phase 0: no internet network at all. Later: Meta API calls go through a separate egress proxy container that may reach only `https://api.meta.ai/v1` (verified by the Oct 27 test; pinned in config); ZeroState reaches the proxy over an internal-only Docker network (brokered pattern, CISA/ACSC AI-in-OT).
15. **Operator container** at 192.168.90.70, router-allowed to reach only the PLC's Modbus port. Suricata write rule loaded for .60 (ZeroState, sid 9100001, must be 0) and .70 (operator, sid 9100002, must be > 0 every episode).
16. **ZeroState can reach only the PLC's Modbus port**: router rule (allow .60 → PLC:502, drop all else from .60) plus an egress allowlist set by a separate network helper container (`zerostate-net`) whose network namespace ZeroState joins with no capabilities, so even root inside ZeroState can't change it (the router never sees same-subnet traffic). C1 is worded exactly that way.
17. **Every threshold names its clock**: process thresholds in process-seconds (`hold_process_s`), converted with the plant's declared `process_time_scale`; freshness windows in wall-clock seconds (`max_static_wall_s`).
18. **Plan and session split**: `IsolationPlan` is hashed and frozen once a person confirms it; `SessionState` (statuses, signatures, timestamps) lives outside it and references the plan hash.
19. **×10 time-scale stability** tested first in Phase 1 (15-min AUTO run at ×10 vs ×1); fallback in decision 8.
20. **Phase 1 reduced** to one live GRFICS episode end to end; plan and process checks and the importer move to Phase 2; claims tooling to Phase 3 morning (see Phases).

## Phases and gates
| Phase | When | Work | Gate |
|---|---|---|---|
| 0 Foundations | Sat Oct 31 | Repo skeleton; live Modbus scan of GRFICS (confirm registers, offset, placeholders); plan schema; read-only Modbus adapter; freshness; network firewall + tests | ZeroState container reads P1 over Modbus and can reach nothing but the PLC's Modbus port |
| 1 Live episode | Sun Nov 1 | GRFICS patch (noise, valve feedback, leak, time scale) + ×10 stability test; freshness path rule (+ placeholder rule decision); live checks; gate; audit log; episode recorder with per-episode IDS counting; operator container (.70) | One live P1 episode runs end to end (operator → patched sim → verdict → audit log); IDS 9100001 = 0 and 9100002 > 0; time scale decided. P2 SPEC.md written in planning chat (not coder work) |
| 2 Second plant + eyes | Mon Nov 2 | P2 model + OPC UA server (if go); plan checks; process checks; camera channel; Muse Spark importer; egress proxy; benchmark run overnight | P2 runs on same engine with only plants/* changed |
| 3 Experience + proof | Tue Nov 3 | Morning: claims.yaml + claims_audit.py; operator page; scoring; claims audit 12:00 ET | Every README number == eval output |
| 4 Ship | Wed Nov 4 | 3-min video, README | Submitted by 6 PM ET (deadline 9 PM ET) |
