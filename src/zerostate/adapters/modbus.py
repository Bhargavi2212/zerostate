"""Read-only Modbus TCP adapter (function codes 1-4 only)."""

from datetime import UTC, datetime
from itertools import groupby
from operator import attrgetter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from zerostate.adapters.freshness import FreshnessTracker
from zerostate.models.signal import Quality, Signal


class MapEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: str
    host: str
    port: int = 502
    table: Literal["ir", "hr", "coil", "di"]
    address: int
    scale_min: float
    scale_max: float
    unit: str
    source_group: str
    placeholder_raw: list[int] = []
    max_static_wall_s: float
    constant_ok_raw: Literal["any"] | list[int] = []
    confirmed: bool = False


class PlantMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process_time_scale: float
    tags: list[MapEntry]


def load_map(path: str | Path) -> PlantMap:
    return PlantMap.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8-sig")))


class ModbusReadOnly:
    def __init__(self, map_path: str | Path, timeout: float = 2.0):
        self.map = load_map(map_path)
        self.entries = {e.tag: e for e in self.map.tags}
        self.timeout = timeout
        self._clients: dict[tuple[str, int], ModbusTcpClient] = {}
        self.freshness = FreshnessTracker(self.map.tags)

    def read(self, tags: list[str] | None = None) -> dict[str, Signal]:
        entries = [self.entries[t] for t in tags] if tags is not None else list(self.entries.values())
        now = datetime.now(UTC)
        out: dict[str, Signal] = {}
        key = attrgetter("host", "port", "table")
        for (host, port, table), group in groupby(sorted(entries, key=attrgetter("host", "port", "table", "address")), key):
            for run in _contiguous(list(group)):
                start = run[0].address
                raws = self._read_run(host, port, table, start, run[-1].address - start + 1)
                for e in run:
                    raw = None if raws is None else int(raws[e.address - start])
                    out[e.tag] = Signal(
                        tag=e.tag,
                        value=None if raw is None else _scale(e, raw),
                        raw=raw,
                        quality=Quality.BAD if raw is None else Quality.GOOD,
                        source_ts=None,  # Modbus carries no source timestamp
                        recv_ts=now,
                    )
        return self.freshness.apply(out)

    def close(self) -> None:
        for c in self._clients.values():
            c.close()

    def _read_run(self, host: str, port: int, table: str, start: int, count: int) -> list | None:
        client = self._clients.setdefault(
            (host, port), ModbusTcpClient(host, port=port, timeout=self.timeout, retries=1)
        )
        try:
            if not client.connected and not client.connect():
                return None
            reads = {
                "ir": client.read_input_registers,
                "hr": client.read_holding_registers,
                "coil": client.read_coils,
                "di": client.read_discrete_inputs,
            }
            rr = reads[table](start, count=count, slave=1)
            if rr.isError():
                return None
            vals = rr.bits if table in ("coil", "di") else rr.registers
            return list(vals[:count]) if len(vals) >= count else None
        except (ModbusException, OSError):
            client.close()
            return None


def _contiguous(entries: list[MapEntry]) -> list[list[MapEntry]]:
    runs: list[list[MapEntry]] = []
    for e in entries:
        if runs and e.address <= runs[-1][-1].address + 1:
            runs[-1].append(e)
        else:
            runs.append([e])
    return runs


def _scale(e: MapEntry, raw: int) -> float:
    if e.table in ("coil", "di"):
        return float(raw)
    return e.scale_min + raw * (e.scale_max - e.scale_min) / 65535
