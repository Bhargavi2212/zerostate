"""Phase 0 read-only scan of the P1 PLC: confirm addresses, offset and placeholder values.

Reads only (FC1/FC3/FC4). JSON samples go to --out; a human summary goes to stderr.
"""

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime

from pymodbus.client import ModbusTcpClient

from zerostate.adapters.modbus import load_map

RANGES = {"ir": [(95, 21)], "hr": [(0, 16), (95, 12)], "coil": [(0, 9)]}


def read_all(client: ModbusTcpClient) -> dict[str, dict[int, int] | None]:
    reads = {
        "ir": client.read_input_registers,
        "hr": client.read_holding_registers,
        "coil": client.read_coils,
    }
    out: dict[str, dict[int, int] | None] = {}
    for table, spans in RANGES.items():
        vals: dict[int, int] | None = {}
        for start, count in spans:
            try:
                rr = reads[table](start, count=count, slave=1)
            except Exception as exc:  # noqa: BLE001 - record any failure, keep scanning
                print(f"{table} {start}+{count}: {exc}", file=sys.stderr)
                vals = None
                break
            if rr.isError():
                vals = None
                break
            data = rr.bits if table == "coil" else rr.registers
            vals.update({start + i: int(v) for i, v in enumerate(data[:count])})
        out[table] = vals
    return out


def offset_check(sample: dict, entries: dict) -> dict[int, bool]:
    """Which address shift makes pressure 2000-3000 kPa and level 20-80 % in normal running."""
    ir = sample["ir"] or {}
    result = {}
    for shift in (-1, 0, 1):
        def scaled(tag, shift=shift):
            e = entries[tag]
            raw = ir.get(e.address + shift)
            return None if raw is None else e.scale_min + raw * (e.scale_max - e.scale_min) / 65535
        p, lv = scaled("pressure"), scaled("level")
        result[shift] = p is not None and lv is not None and 2000 <= p <= 3000 and 20 <= lv <= 80
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=1)
    ap.add_argument("--out", default=None)
    ap.add_argument("--map", default=os.environ.get("ZS_MAP", "/app/config/p1_grfics/modbus_map.yaml"))
    args = ap.parse_args()

    entries = {e.tag: e for e in load_map(args.map).tags}
    host = entries["pressure"].host
    client = ModbusTcpClient(host, port=entries["pressure"].port, timeout=2, retries=1)
    samples = []
    for _ in range(args.seconds):
        t0 = time.monotonic()
        if not client.connected:
            client.connect()
        sample = {"t": datetime.now(UTC).isoformat(), **read_all(client)}
        samples.append(sample)
        ir = sample["ir"] or {}
        print(f"{sample['t']} pressure_raw={ir.get(entries['pressure'].address)} "
              f"level_raw={ir.get(entries['level'].address)}", file=sys.stderr)
        time.sleep(max(0.0, 1 - (time.monotonic() - t0)))
    client.close()

    checks = offset_check(samples[-1], entries)
    print(f"offset check (shift -> plausible pressure+level): {checks}", file=sys.stderr)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"host": host, "ranges": RANGES, "offset_check": checks, "samples": samples}, f, indent=1)
    return 0 if checks[0] else 1


if __name__ == "__main__":
    sys.exit(main())
