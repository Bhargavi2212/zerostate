"""Eval only: the P1 operator. Performs isolation steps through the PLC's own manual mode, as a
human at the HMI would. Not ZeroState: lives under plants/, never imported by src/zerostate.

Writes only coil 0 (manual_mode) and HR10-13 (manual setpoints), each followed by a readback.

    python operator.py status
    python operator.py manual on|off
    python operator.py set <f1|f2|purge|product> <pct>
    python operator.py wait-pressure-below <kPa> --mean-of 8 --timeout-process-s N --process-time-scale S
    python operator.py wait-valve <v> <pct> --tol 1 --timeout-process-s 120 --process-time-scale S
"""

import argparse
import json
import os
import sys
import time
from collections import deque

from pymodbus.client import ModbusTcpClient

VALVES = ("f1", "f2", "purge", "product")
SETPOINT_HR = {v: 10 + i for i, v in enumerate(VALVES)}  # %QW10-13
COMMAND_HR = 100  # %QW100-103, PLC outputs
FEEDBACK_IR = {v: 100 + 2 * i for i, v in enumerate(VALVES)}  # %IW100, 102, 104, 106
FLOW_IR = {v: 101 + 2 * i for i, v in enumerate(VALVES)}
PRESSURE_IR, LEVEL_IR = 108, 109
DEFAULT_SETPOINTS = [0, 0, 65535, 65535]  # PLC program defaults: feeds closed, purge/product open
FLOW_SPAN = {"f1": 1000, "f2": 500, "purge": 2000, "product": 500}


class OperatorError(Exception):
    """A write did not read back as written: stop rather than act on an unknown state."""


def pct(raw: int) -> float:
    return raw * 100 / 65535


def raw_of(p: float) -> int:
    return max(0, min(65535, round(p * 65535 / 100)))


class Operator:
    def __init__(self, host: str, port: int = 502, timeout: float = 2.0):
        self.c = ModbusTcpClient(host, port=port, timeout=timeout, retries=1)
        if not self.c.connect():
            raise OperatorError(f"cannot connect to PLC {host}:{port}")

    def _ir(self, start: int, count: int) -> list[int]:
        rr = self.c.read_input_registers(start, count=count, slave=1)
        if rr.isError():
            raise OperatorError(f"read IR {start}+{count} failed")
        return list(rr.registers)

    def _hr(self, start: int, count: int) -> list[int]:
        rr = self.c.read_holding_registers(start, count=count, slave=1)
        if rr.isError():
            raise OperatorError(f"read HR {start}+{count} failed")
        return list(rr.registers)

    def _coil(self) -> bool:
        rr = self.c.read_coils(0, count=1, slave=1)
        if rr.isError():
            raise OperatorError("read coil 0 failed")
        return bool(rr.bits[0])

    def _write_setpoints(self, start: int, values: list[int]) -> None:
        self.c.write_registers(start, values, slave=1)
        back = self._hr(start, len(values))
        if back != values:
            raise OperatorError(f"setpoint readback {back} != written {values}")

    def _write_mode(self, on: bool) -> None:
        self.c.write_coil(0, on, slave=1)
        if self._coil() != on:
            raise OperatorError(f"manual_mode readback != {on}")

    def status(self) -> dict:
        ir = self._ir(100, 13)
        return {
            "pressure_kpa": round(ir[PRESSURE_IR - 100] * 3200 / 65535, 1),
            "level_pct": round(pct(ir[LEVEL_IR - 100]), 2),
            "feedback_pct": {v: round(pct(ir[FEEDBACK_IR[v] - 100]), 2) for v in VALVES},
            "flow": {v: round(ir[FLOW_IR[v] - 100] * FLOW_SPAN[v] / 65535, 1) for v in VALVES},
            "command_pct": dict(zip(VALVES, (round(pct(r), 2) for r in self._hr(COMMAND_HR, 4)), strict=True)),
            "manual_setpoint_pct": dict(zip(VALVES, (round(pct(r), 2) for r in self._hr(10, 4)), strict=True)),
            "manual_mode": self._coil(),
        }

    def manual_on(self) -> None:
        # Bumpless: copy the PLC's current commands into the manual setpoints before switching,
        # otherwise the program's defaults (feeds closed, purge/product open) would apply at once.
        self._write_setpoints(10, self._hr(COMMAND_HR, 4))
        self._write_mode(True)

    def manual_off(self) -> None:
        self._write_mode(False)
        self._write_setpoints(10, list(DEFAULT_SETPOINTS))

    def set(self, valve: str, p: float) -> None:
        self._write_setpoints(SETPOINT_HR[valve], [raw_of(p)])

    def wait_pressure_below(self, kpa: float, mean_of: int, timeout_wall_s: float, poll_s: float = 0.25) -> bool:
        window: deque[float] = deque(maxlen=mean_of)
        end = time.monotonic() + timeout_wall_s
        while time.monotonic() < end:
            window.append(self._ir(PRESSURE_IR, 1)[0] * 3200 / 65535)
            if len(window) == mean_of and sum(window) / mean_of < kpa:
                return True
            time.sleep(poll_s)
        return False

    def wait_valve(self, valve: str, p: float, tol: float, timeout_wall_s: float, poll_s: float = 0.25) -> bool:
        end = time.monotonic() + timeout_wall_s
        while time.monotonic() < end:
            if abs(pct(self._ir(FEEDBACK_IR[valve], 1)[0]) - p) <= tol:
                return True
            time.sleep(poll_s)
        return False

    def close(self) -> None:
        self.c.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("ZS_PLC", "192.168.95.2"))
    ap.add_argument("--port", type=int, default=502)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    m = sub.add_parser("manual")
    m.add_argument("state", choices=["on", "off"])
    s = sub.add_parser("set")
    s.add_argument("valve", choices=VALVES)
    s.add_argument("pct", type=float)
    for name in ("wait-pressure-below", "wait-valve"):
        w = sub.add_parser(name)
        if name == "wait-valve":
            w.add_argument("valve", choices=VALVES)
            w.add_argument("pct", type=float)
            w.add_argument("--tol", type=float, default=1.0)
        else:
            w.add_argument("kpa", type=float)
            w.add_argument("--mean-of", type=int, default=8)
        w.add_argument("--timeout-process-s", type=float, required=True)
        w.add_argument("--process-time-scale", type=float, required=True)
    a = ap.parse_args(argv)

    op = Operator(a.host, a.port)
    try:
        if a.cmd == "status":
            print(json.dumps(op.status()))
        elif a.cmd == "manual":
            op.manual_on() if a.state == "on" else op.manual_off()
        elif a.cmd == "set":
            op.set(a.valve, a.pct)
        elif a.cmd == "wait-pressure-below":
            return 0 if op.wait_pressure_below(a.kpa, a.mean_of, a.timeout_process_s / a.process_time_scale) else 2
        elif a.cmd == "wait-valve":
            return 0 if op.wait_valve(a.valve, a.pct, a.tol, a.timeout_process_s / a.process_time_scale) else 2
    except OperatorError as e:
        print(f"ABORT: {e}", file=sys.stderr)
        return 1
    finally:
        op.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
