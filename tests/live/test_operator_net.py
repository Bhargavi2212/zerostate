"""Gate 4: the operator container reaches the PLC's Modbus port and not the simulator's truth."""

import subprocess

import pytest

pytestmark = pytest.mark.live

PROBE = (
    "import socket,sys\n"
    "try:\n"
    "    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=2).close(); print('open')\n"
    "except OSError:\n"
    "    print('closed')\n"
)


def reach(host: str, port: int) -> str:
    r = subprocess.run(["docker", "exec", "zs-operator", "python", "-c", PROBE, host, str(port)],
                       capture_output=True, text=True, timeout=30, check=True)
    return r.stdout.strip()


def test_operator_reaches_plc_modbus():
    assert reach("192.168.95.2", 502) == "open"


@pytest.mark.parametrize(("host", "port"), [("192.168.95.45", 80), ("192.168.95.45", 55555)])
def test_operator_cannot_reach_truth(host, port):
    assert reach(host, port) == "closed"
