# ZeroState — measured behaviour of Meta models

Only measured results go here, with date and setup. This file feeds the README section on the models. Wording rules: PROJECT.md "never say" list.

## Oct 27 — first test (`D:\grfics\zerostate_test.py`, GRFICS 3D view)
- SAM 3.1 found tanks (score ~0.94) and displays (~0.8). It found **zero** "valve" objects, so a valve is located as the actuator under its display plus a layout map.
- Muse Spark read close-up digital displays correctly 6 of 7 times, after correcting for the timing between frame capture and plant data.
- Muse Spark returned "unreadable" on tiny crops → crop and upscale before reading.
