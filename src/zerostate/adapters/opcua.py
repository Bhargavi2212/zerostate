"""Read-only OPC UA adapter (asyncua sync client, Read service only, user `zerostate`).

Same contract as modbus.py: read(tags) -> {tag: Signal}. Quality comes from the StatusCode (Bad -> BAD,
Uncertain -> UNKNOWN), freshness from the SourceTimestamp (missing or older than max_age_wall_s -> STALE)
on top of the noise-loss rule in freshness.py, which sees each value quantised to 16 bits of its span
like a Modbus register. The password comes from the environment only (P2_PASSWORD_ZEROSTATE, the same name the P2 server reads: one name per secret).
"""

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from asyncua import ua
from asyncua.sync import Client
from pydantic import BaseModel, ConfigDict

from zerostate.adapters.freshness import FreshnessTracker
from zerostate.models.signal import Quality, Signal


class OpcEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: str
    node: str  # e.g. ns=2;s=PT-211.PV
    host: str = "opcua"  # one server: one shared path for the dead-host rule
    scale_min: float
    scale_max: float
    unit: str
    source_group: str
    placeholder_raw: list[int] = []
    max_static_wall_s: float
    constant_ok_raw: Literal["any"] | list[int] = []


class OpcMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: Literal["opcua"]
    endpoint: str
    user: str = "zerostate"
    process_time_scale: float
    max_age_wall_s: float  # SourceTimestamp older than this -> STALE
    tags: list[OpcEntry]


def load_map(path: str | Path) -> OpcMap:
    return OpcMap.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8-sig")))


def to_signal(e: OpcEntry, dv: ua.DataValue | None, now: datetime, max_age_wall_s: float) -> Signal:
    """One DataValue -> Signal, before the noise rule."""
    status = dv.StatusCode if dv is not None else None
    value = dv.Value.Value if dv is not None and dv.Value is not None else None
    if status is None or status.is_bad() or not isinstance(value, (int, float)):
        return Signal(tag=e.tag, value=None, raw=None, quality=Quality.BAD, source_ts=None, recv_ts=now)
    src = dv.SourceTimestamp.replace(tzinfo=UTC) if dv.SourceTimestamp and dv.SourceTimestamp.tzinfo is None else dv.SourceTimestamp
    if not status.is_good():
        q = Quality.UNKNOWN  # Uncertain
    elif src is None or (now - src).total_seconds() > max_age_wall_s:
        q = Quality.STALE
    else:
        q = Quality.GOOD
    raw = round((float(value) - e.scale_min) / (e.scale_max - e.scale_min) * 65535)
    return Signal(tag=e.tag, value=float(value), raw=min(max(raw, 0), 65535), quality=q, source_ts=src, recv_ts=now)


class OpcUaReadOnly:
    def __init__(self, map_path: str | Path, timeout: float = 2.0, now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.map = load_map(map_path)
        self.entries = {e.tag: e for e in self.map.tags}
        self.timeout, self.now = timeout, now
        self._client: Client | None = None
        self.freshness = FreshnessTracker(self.map.tags)

    def _connect(self) -> Client:
        if self._client is None:
            c = Client(self.map.endpoint, timeout=self.timeout, sync_wrapper_timeout=3 * self.timeout)
            c.set_user(self.map.user)
            c.set_password(os.environ.get("P2_PASSWORD_ZEROSTATE", ""))
            try:
                c.connect()
            except BaseException:
                c.tloop.stop()
                raise
            self._client = c
        return self._client

    def read(self, tags: list[str] | None = None) -> dict[str, Signal]:
        entries = [self.entries[t] for t in tags] if tags is not None else list(self.entries.values())
        if not entries:
            return {}
        try:
            c = self._connect()
            dvs = c.read_attributes([c.get_node(e.node) for e in entries], ua.AttributeIds.Value)
        except (ua.UaError, OSError, TimeoutError, RuntimeError):  # server down, session lost, timeout: all BAD, reconnect next poll
            self.close()
            dvs = [None] * len(entries)
        now = self.now()
        out = {e.tag: to_signal(e, dv, now, self.map.max_age_wall_s) for e, dv in zip(entries, dvs, strict=True)}
        return self.freshness.apply(out)

    def close(self) -> None:
        c, self._client = self._client, None
        if c is not None:
            try:
                c.disconnect()
            except (ua.UaError, OSError, TimeoutError, RuntimeError):
                c.tloop.stop()
