# Invalid episode — does not count (runner race)

The runner opened purge for the vent *before* marking step 5, while ZeroState's continuous monitor
still listed purge as blocked in since step 2, so LIVE-VALVE blocked with "commanded state wrong:
purge_cmd = 100 %". That is a runner ordering bug, not a plant fault or a ZeroState error. Fixed in
d7a1c68 (declare the step, wait until ZeroState registers it, then act); the same scenario and seed
were re-run and count instead.
