# Invalid episode — does not count

The comms-loss fault never happened: `supervisorctl stop modbus` stopped only `run_all.sh`; the six
I/O device scripts it had started in the background kept serving fresh data (20/20 distinct pressure
raws after the "fault", see `events.jsonl` for its time). ZeroState correctly saw a live plant and
returned NO_DISCREPANCY. The runner at that commit could not detect a fault that failed to apply, so
`verdict.json` still says `valid: true`; it is left unedited as evidence. Since commit `2c50af6` the
runner kills the device processes, verifies every fault took effect, and marks such episodes invalid.
Re-run: `S12_seed19_20261101T184743` (ESCALATED, valid).
