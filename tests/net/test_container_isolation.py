"""C1, run inside the zerostate container (gate runs it as root, the worst case).

ZeroState may reach the PLC's Modbus port and nothing else, and cannot change that.
"""

import os
import shutil
import socket
import subprocess

import pytest

from zerostate.adapters.modbus import ModbusReadOnly
from zerostate.models.signal import Quality

pytestmark = pytest.mark.net

PLC = ("192.168.95.2", 502)
BLOCKED = [
    ("192.168.95.45", 80),  # simulator truth web API
    ("192.168.95.45", 55555),  # simulator JSON socket
    ("192.168.95.10", 502),  # remote I/O, bypasses the PLC
    ("192.168.95.2", 8080),  # OpenPLC web UI (can upload programs)
    ("host.docker.internal", 80),  # Windows-published truth
    ("host.docker.internal", 8080),
    ("192.168.90.107", 8080),  # HMI, same DMZ subnet (never reaches the router)
    ("192.168.90.200", 80),  # the router itself
    ("1.1.1.1", 443),  # internet
]


def connects(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=2).close()
        return True
    except OSError:  # includes name-resolution failure and timeout
        return False


def test_plc_modbus_reachable_and_readable():
    assert connects(*PLC)
    adapter = ModbusReadOnly(os.environ["ZS_MAP"])
    s = adapter.read(["pressure"])["pressure"]
    adapter.close()
    assert s.quality == Quality.GOOD and 0 < s.value < 3200


@pytest.mark.parametrize(("host", "port"), BLOCKED)
def test_everything_else_unreachable(host, port):
    assert not connects(host, port)


def test_ipv6_off_or_dropped():
    with open("/proc/sys/net/ipv6/conf/all/disable_ipv6") as f:
        if f.read().strip() == "1":
            return
    with pytest.raises(OSError):
        socket.create_connection(("ff02::1%eth0", 80), timeout=2).close()


@pytest.mark.parametrize(
    "cmd",
    [
        ["iptables", "-A", "OUTPUT", "-j", "ACCEPT"],
        ["ip6tables", "-A", "OUTPUT", "-j", "ACCEPT"],
        ["ip", "route", "add", "10.99.0.0/16", "via", "192.168.90.200"],
    ],
)
def test_cannot_change_network(cmd):
    assert shutil.which(cmd[0]), f"{cmd[0]} missing: test would pass for the wrong reason"
    r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10)
    assert r.returncode != 0
    assert "denied" in (r.stderr + r.stdout).lower() or "not permitted" in (r.stderr + r.stdout).lower()


def test_no_effective_capabilities():
    with open("/proc/self/status") as f:
        cap_eff = next(line.split()[1] for line in f if line.startswith("CapEff:"))
    assert int(cap_eff, 16) == 0
