"""P2-9, run inside the zs-api container: `docker exec zs-api pytest -m net tests/net/test_api_isolation.py`.

The API reaches the model proxy and nothing else (never a plant), cannot change that, and cannot write
the audit log (its volume is mounted read-only).
"""

import os
import socket
import sqlite3
import subprocess

import pytest

from zerostate.audit.log import AuditLog

pytestmark = pytest.mark.net

PROXY = ("172.30.0.2", 8888)
BLOCKED = [
    ("192.168.95.2", 502),  # P1 PLC Modbus
    ("192.168.95.50", 4840),  # P2 OPC UA
    ("192.168.95.45", 80),  # simulator
    ("172.30.0.3", 8080),  # frame service
    ("172.30.0.2", 22),  # proxy, any other port
    ("host.docker.internal", 80),
    ("1.1.1.1", 443),  # internet
]


def connects(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=2).close()
        return True
    except OSError:
        return False


def test_proxy_reachable():
    assert connects(*PROXY)


@pytest.mark.parametrize(("host", "port"), BLOCKED)
def test_everything_else_unreachable(host, port):
    assert not connects(host, port)


def test_cannot_change_the_allowlist():
    r = subprocess.run(["iptables", "-P", "OUTPUT", "ACCEPT"], check=False, capture_output=True)
    assert r.returncode != 0


def test_audit_log_is_read_only():
    path = os.environ["ZS_AUDIT"]
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(path).execute("CREATE TABLE IF NOT EXISTS zs_api_probe (x)")
    with pytest.raises(sqlite3.OperationalError):
        AuditLog(path, read_only=True).append("zs-api-probe", "probe", {})
