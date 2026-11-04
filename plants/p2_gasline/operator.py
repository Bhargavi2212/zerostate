"""Eval only: the P2 operator. Performs isolation steps on the gas line over OPC UA as the `operator`
user (password from P2_PASSWORD_OPERATOR, never printed or logged), as a field operator would. Not
ZeroState: lives under plants/, never imported by src/zerostate. In the zs-operator image as operator_p2.py.

Writes only <VALVE>.CMD (the server allows `operator` nothing else), each followed by a readback.

    python operator_p2.py status
    python operator_p2.py set <XV-201|BV-202|XV-203|VV-213|XV-204|XV-231> <pct>
    python operator_p2.py wait-pressure-below <PT-tag> <kPa> --mean-of 8 --timeout-process-s N --process-time-scale S

Exit codes like plants/p1_grfics/operator.py: 0 done, 1 abort (connection or readback), 2 wait timed out.
"""

import argparse
import json
import os
import sys
import time
from collections import deque
from datetime import UTC, datetime

VALVES = ("XV-201", "BV-202", "XV-203", "VV-213", "XV-204", "XV-231")
GAUGES = ("PT-200", "PT-202", "PT-211", "PT-212")


class OperatorError(Exception):
    """A write did not read back as written: stop rather than act on an unknown state."""


class Operator:
    def __init__(self, endpoint: str, client=None):
        if client is None:
            from asyncua.sync import Client  # imported here so the tests need no server
            client = Client(endpoint, timeout=4)
            client.set_user("operator")
            client.set_password(os.environ.get("P2_PASSWORD_OPERATOR", ""))
            try:
                client.connect()
            except Exception as e:  # noqa: BLE001 - any connection failure is an abort, password never shown
                client.tloop.stop()  # its thread would otherwise keep the process alive
                raise OperatorError(f"cannot connect to {endpoint} as operator: {type(e).__name__}") from None
        self.c = client

    def _value(self, node: str) -> float:
        return float(self.c.get_node(f"ns=2;s={node}").read_value())

    def set(self, valve: str, pct: float) -> None:
        from asyncua import ua
        node = self.c.get_node(f"ns=2;s={valve}.CMD")
        # stamped like every server-published value: an unstamped write reads STALE until the next tick (seed 310)
        now = datetime.now(UTC)
        node.write_value(ua.DataValue(ua.Variant(float(pct), ua.VariantType.Double), SourceTimestamp=now, ServerTimestamp=now))
        if abs(self._value(f"{valve}.CMD") - pct) > 1e-6:
            raise OperatorError(f"{valve}.CMD readback != {pct}")

    def status(self) -> dict:
        return {"pressure_kpa": {g: round(self._value(f"{g}.PV"), 1) for g in GAUGES},
                "feedback_pct": {v: round(self._value(f"{v}.FB"), 2) for v in VALVES},
                "command_pct": {v: round(self._value(f"{v}.CMD"), 2) for v in VALVES}}

    def wait_pressure_below(self, gauge: str, kpa: float, mean_of: int, timeout_wall_s: float, poll_s: float = 0.25) -> bool:
        window: deque[float] = deque(maxlen=mean_of)
        end = time.monotonic() + timeout_wall_s
        while time.monotonic() < end:
            window.append(self._value(f"{gauge}.PV"))
            if len(window) == mean_of and sum(window) / mean_of < kpa:
                return True
            time.sleep(poll_s)
        return False

    def close(self) -> None:
        self.c.disconnect()


def main(argv: list[str] | None = None, client=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default=os.environ.get("ZS_P2_ENDPOINT", "opc.tcp://192.168.95.50:4840/"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    s = sub.add_parser("set")
    s.add_argument("valve", choices=VALVES)
    s.add_argument("pct", type=float)
    w = sub.add_parser("wait-pressure-below")
    w.add_argument("gauge", choices=GAUGES)
    w.add_argument("kpa", type=float)
    w.add_argument("--mean-of", type=int, default=8)
    w.add_argument("--timeout-process-s", type=float, required=True)
    w.add_argument("--process-time-scale", type=float, required=True)
    a = ap.parse_args(argv)
    try:
        op = Operator(a.endpoint, client)
    except OperatorError as e:
        print(f"ABORT: {e}", file=sys.stderr)
        return 1
    try:
        if a.cmd == "status":
            print(json.dumps(op.status()))
        elif a.cmd == "set":
            op.set(a.valve, a.pct)
        elif a.cmd == "wait-pressure-below":
            return 0 if op.wait_pressure_below(a.gauge, a.kpa, a.mean_of, a.timeout_process_s / a.process_time_scale) else 2
    except OperatorError as e:
        print(f"ABORT: {e}", file=sys.stderr)
        return 1
    finally:
        op.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
