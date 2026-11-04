"""C1, run inside the zerostate container (gate runs it as root, the worst case).

ZeroState may reach the PLC's Modbus port and nothing else, and cannot change that.
"""

import os
import shutil
import socket
import subprocess
import time

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
    ("192.168.95.2", 4840),  # OPC UA anywhere but P2
    ("192.168.95.45", 4840),
    ("192.168.95.51", 4840),
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
    first = adapter.read(["pressure"])["pressure"]
    for _ in range(5):  # a live reading must be seen changing before it is GOOD
        time.sleep(1)
        s = adapter.read(["pressure"])["pressure"]
        if s.quality == Quality.GOOD:
            break
    adapter.close()
    assert first.quality == Quality.UNKNOWN
    assert s.quality == Quality.GOOD and 0 < s.value < 3200


P2 = ("192.168.95.50", 4840)
P2_UP = pytest.mark.skipif(not os.environ.get("ZS_NET_P2"), reason="P2 checks run only with P2 live: docker exec -e ZS_NET_P2=1 ...")


@P2_UP
def test_p2_opcua_reachable():
    assert connects(*P2)


@P2_UP
def test_zerostate_account_cannot_write_p2():
    """ZeroState's own OPC UA account (`zerostate`) tries one *.CMD write: the server must refuse it and
    the value must not change. Password from P2_PASSWORD_ZEROSTATE, never printed."""
    from asyncua import ua
    from asyncua.sync import Client

    if not connects(*P2):
        pytest.skip("P2 OPC UA endpoint unreachable (P2 not up)")
    c = Client(f"opc.tcp://{P2[0]}:{P2[1]}/", timeout=5)
    c.set_user("zerostate")
    c.set_password(os.environ.get("P2_PASSWORD_ZEROSTATE", ""))
    c.connect()
    try:
        node = c.get_node("ns=2;s=XV-231.CMD")
        before = node.read_value()
        with pytest.raises(ua.UaStatusCodeError) as e:
            node.write_value(ua.DataValue(ua.Variant(float(before) + 7.0, ua.VariantType.Double)))
        assert not ua.StatusCode(e.value.code).is_good()  # BadUserAccessDenied from the server's own check
        time.sleep(1)
        assert node.read_value() == before
    finally:
        c.disconnect()


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


# ---------------------------------------------------------------- Phase 2: egress proxy (decision 14)
PROXY = ("172.30.0.2", 8888)


def via_proxy(request: bytes) -> str:
    """Send one raw request to the proxy; return its status line."""
    with socket.create_connection(PROXY, timeout=10) as s:
        s.sendall(request)
        return s.recv(4096).split(b"\r\n", 1)[0].decode(errors="replace")


def test_proxy_tunnels_only_to_the_meta_api_with_tls_end_to_end():
    import ssl

    s = socket.create_connection(PROXY, timeout=10)
    s.sendall(b"CONNECT api.meta.ai:443 HTTP/1.1\r\nHost: api.meta.ai:443\r\n\r\n")
    assert b" 200" in s.recv(4096).split(b"\r\n", 1)[0]
    tls = ssl.create_default_context().wrap_socket(s, server_hostname="api.meta.ai")  # handshake only, no API call
    assert tls.version()
    tls.close()


@pytest.mark.parametrize("request_line", [
    b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n",
    b"CONNECT host.docker.internal:80 HTTP/1.1\r\nHost: host.docker.internal:80\r\n\r\n",
    b"CONNECT api.meta.ai:80 HTTP/1.1\r\nHost: api.meta.ai:80\r\n\r\n",
    b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n",
])
def test_proxy_refuses_everything_else(request_line):
    assert " 403" in via_proxy(request_line)
