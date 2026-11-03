"""P2-6: read-only OPC UA adapter against the in-process P2 server: values, StatusCode quality,
SourceTimestamp freshness, server down -> BAD; the CLI picks the adapter from the map's protocol."""

import socket
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from asyncua import ua
from conftest import P2_USERS

from zerostate.adapters.modbus import ModbusReadOnly
from zerostate.adapters.opcua import OpcUaReadOnly, load_map, to_signal
from zerostate.cli import open_adapter
from zerostate.models.signal import Quality

ROOT = Path(__file__).parents[1]
P2_MAP = ROOT / "plants" / "p2_gasline" / "opcua_map.yaml"


def local_map(tmp_path, url):
    m = yaml.safe_load(P2_MAP.read_text(encoding="utf-8"))
    m["endpoint"] = url
    p = tmp_path / "opcua_map.yaml"
    p.write_text(yaml.safe_dump(m))
    return p


@pytest.fixture
def adapter(p2_server, tmp_path, monkeypatch):
    url, plant, _ = p2_server
    plant.control({"request": "updates", "on": True})
    monkeypatch.setenv("ZS_OPCUA_PASSWORD", P2_USERS["zerostate"])
    a = OpcUaReadOnly(local_map(tmp_path, url))
    yield a, plant
    a.close()


def test_reads_values_good_once_seen_changing(adapter):
    a, _ = adapter
    first = a.read()
    assert set(first) == {e.tag for e in load_map(P2_MAP).tags}
    assert first["XV-201.FB"].quality == Quality.GOOD and first["XV-201.FB"].value == 100
    assert first["PT-211"].quality == Quality.UNKNOWN  # noise-carrying: must be seen changing first
    time.sleep(0.2)
    s = a.read(["PT-211", "PT-212", "FT-213"])
    assert s["PT-211"].quality == Quality.GOOD and 1500 < s["PT-211"].value < 2000
    assert s["PT-211"].source_ts is not None and abs(s["PT-211"].value - s["PT-212"].value) < 10
    assert a.read([]) == {}


def test_old_source_timestamp_is_stale(adapter):
    a, plant = adapter
    a.read()
    time.sleep(0.2)
    assert a.read(["PT-211"])["PT-211"].quality == Quality.GOOD
    plant.control({"request": "updates", "on": False})  # S12: the server stops updating
    a.now = lambda: datetime.now(UTC) + timedelta(seconds=a.map.max_age_wall_s + 1)
    s = a.read()
    assert {v.quality for v in s.values()} == {Quality.STALE}


def test_status_code_sets_quality():
    e = load_map(P2_MAP).tags[0]
    now = datetime.now(UTC)

    def dv(code):
        return ua.DataValue(ua.Variant(150.0, ua.VariantType.Double), StatusCode_=ua.StatusCode(code), SourceTimestamp=now)

    assert to_signal(e, dv(ua.StatusCodes.Good), now, 2).quality == Quality.GOOD
    assert to_signal(e, dv(ua.StatusCodes.UncertainLastUsableValue), now, 2).quality == Quality.UNKNOWN
    bad = to_signal(e, dv(ua.StatusCodes.BadSensorFailure), now, 2)
    assert bad.quality == Quality.BAD and bad.value is None
    no_ts = ua.DataValue(ua.Variant(150.0, ua.VariantType.Double), StatusCode_=ua.StatusCode(ua.StatusCodes.Good))
    assert to_signal(e, no_ts, now, 2).quality == Quality.STALE


def test_server_down_or_wrong_user_gives_bad(tmp_path, monkeypatch, p2_server):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    a = OpcUaReadOnly(local_map(tmp_path, f"opc.tcp://127.0.0.1:{port}/"), timeout=0.5)
    assert {v.quality for v in a.read(["PT-211", "XV-201.FB"]).values()} == {Quality.BAD}
    a.close()
    monkeypatch.setenv("ZS_OPCUA_PASSWORD", "wrong")
    b = OpcUaReadOnly(local_map(tmp_path, p2_server[0]), timeout=1)
    s = b.read(["PT-211"])
    b.close()
    assert s["PT-211"].quality == Quality.BAD and s["PT-211"].value is None


def test_unknown_tag_raises():
    with pytest.raises(KeyError):
        OpcUaReadOnly(P2_MAP).read(["nope"])


def test_cli_picks_adapter_from_protocol():
    a = open_adapter(P2_MAP)
    assert isinstance(a, OpcUaReadOnly) and a.map.process_time_scale == 30
    assert isinstance(open_adapter(ROOT / "plants" / "p1_grfics" / "modbus_map.yaml"), ModbusReadOnly)
