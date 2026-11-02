# Superseded — LIVE-QUALITY v1 false trip (tuning seed), re-run under v2

LIVE-QUALITY v1 measured the rate of change across a single poll; a late poll carrying a stale
pressure value read as an impossible change and blocked this episode before its scenario finished
(for S1b, before its fault was even injected). v2 measures over a 20 process-s baseline (DECISIONS,
Nov 1). `zs replay` of this episode under v2 reports exactly that difference: the logged FAIL now
evaluates PASS. The same scenario and seed were re-run live under v2 and count instead.
