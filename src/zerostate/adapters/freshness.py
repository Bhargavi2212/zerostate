"""Infer freshness for sources without timestamps: placeholder values and loss of process noise."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from zerostate.models.signal import Quality, Signal

if TYPE_CHECKING:
    from zerostate.adapters.modbus import MapEntry


class FreshnessTracker:
    def __init__(self, entries: Iterable[MapEntry], clock: Callable[[], float] = time.monotonic):
        self.entries = {e.tag: e for e in entries}
        self.clock = clock
        self._last: dict[str, tuple[int, float]] = {}  # tag -> (raw, wall time it last changed)
        self._seen_change: set[str] = set()  # a tag must be seen changing before it can be GOOD

    def static_for_s(self, tag: str) -> float | None:
        last = self._last.get(tag)
        return None if last is None else self.clock() - last[1]

    def apply(self, signals: dict[str, Signal]) -> dict[str, Signal]:
        now = self.clock()
        out = dict(signals)
        noisy_static: dict[str, list[bool]] = defaultdict(list)
        for tag, s in signals.items():
            if s.quality != Quality.GOOD or s.raw is None:
                continue
            e = self.entries[tag]
            last = self._last.get(tag)
            if last is None or last[0] != s.raw:
                self._last[tag] = (s.raw, now)
                if last is not None:
                    self._seen_change.add(tag)
            if s.raw in e.placeholder_raw:
                out[tag] = s.model_copy(update={"quality": Quality.UNKNOWN})
                continue
            if e.constant_ok_raw == "any" or s.raw in e.constant_ok_raw:
                continue
            static = now - self._last[tag][1] > e.max_static_wall_s
            noisy_static[e.source_group].append(static)
            if static:
                out[tag] = s.model_copy(update={"quality": Quality.STALE})
            elif tag not in self._seen_change:
                # Not yet seen alive: frozen data would look fresh until the window ran out.
                out[tag] = s.model_copy(update={"quality": Quality.UNKNOWN})
        # A group is dead only if it has noise-carrying tags and every one of them stopped changing.
        dead = {g for g, flags in noisy_static.items() if flags and all(flags)}
        for tag, s in out.items():
            if self.entries[tag].source_group in dead and s.quality != Quality.BAD:
                out[tag] = s.model_copy(update={"quality": Quality.STALE})
        return out
