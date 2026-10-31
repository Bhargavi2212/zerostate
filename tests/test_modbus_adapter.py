import asyncio
import socket
import threading
import time

import pytest
import yaml
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.server import ServerAsyncStop, StartAsyncTcpServer

from zerostate.adapters.modbus import ModbusReadOnly
from zerostate.models.signal import Quality


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server():
    port = free_port()
    ir = [0] * 200
    ir[100], ir[101], ir[108] = 32768, 65535, 55296  # f1_valve_pos, f1_flow, pressure
    hr = [0] * 200
    hr[100] = 13107
    co = [False] * 16
    co[0] = True
    # Block starts at 1: pymodbus servers add 1 to the requested address.
    # di must be passed: pymodbus 3.9.2 ignores co/ir/hr when di is None.
    ctx = ModbusServerContext(
        slaves=ModbusSlaveContext(
            di=ModbusSequentialDataBlock(1, [False] * 16),
            ir=ModbusSequentialDataBlock(1, ir),
            hr=ModbusSequentialDataBlock(1, hr),
            co=ModbusSequentialDataBlock(1, co),
        ),
        single=True,
    )
    loop = asyncio.new_event_loop()
    t = threading.Thread(
        target=lambda: loop.run_until_complete(StartAsyncTcpServer(ctx, address=("127.0.0.1", port))),
        daemon=True,
    )
    t.start()
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
            break
        except OSError:
            time.sleep(0.05)

    def stop():
        asyncio.run_coroutine_threadsafe(ServerAsyncStop(), loop).result(5)
        t.join(5)

    yield port, stop
    if t.is_alive():
        stop()


def write_map(tmp_path, port):
    base = {"host": "127.0.0.1", "port": port, "unit": "x", "source_group": "g", "max_static_wall_s": 10}
    tags = [
        dict(base, tag="f1_valve_pos", table="ir", address=100, scale_min=0, scale_max=100, constant_ok_raw="any"),
        dict(base, tag="f1_flow", table="ir", address=101, scale_min=0, scale_max=1000),
        dict(base, tag="pressure", table="ir", address=108, scale_min=0, scale_max=3200),
        dict(base, tag="f1_cmd", table="hr", address=100, scale_min=0, scale_max=100),
        dict(base, tag="manual_mode", table="coil", address=0, scale_min=0, scale_max=1),
    ]
    p = tmp_path / "map.yaml"
    p.write_text(yaml.safe_dump({"process_time_scale": 1, "tags": tags}))
    return p


def test_reads_and_scales(server, tmp_path):
    port, _ = server
    a = ModbusReadOnly(write_map(tmp_path, port))
    s = a.read()
    a.close()
    # First sight of a noise-carrying tag is UNKNOWN until it is seen changing (freshness).
    assert s["pressure"].quality == Quality.UNKNOWN and s["f1_valve_pos"].quality == Quality.GOOD
    assert a.read([]) == {}
    assert s["f1_valve_pos"].value == pytest.approx(50, abs=0.01)
    assert s["f1_flow"].value == pytest.approx(1000)
    assert s["pressure"].value == pytest.approx(2700, abs=0.1)
    assert s["f1_cmd"].value == pytest.approx(20, abs=0.01)
    assert s["manual_mode"].raw == 1 and s["manual_mode"].source_ts is None


def test_server_down_gives_bad(server, tmp_path):
    port, stop = server
    a = ModbusReadOnly(write_map(tmp_path, port), timeout=0.5)
    stop()
    s = a.read(["pressure", "manual_mode"])
    a.close()
    assert {v.quality for v in s.values()} == {Quality.BAD}
    assert all(v.value is None for v in s.values())


def test_unknown_tag_raises(tmp_path):
    a = ModbusReadOnly(write_map(tmp_path, 1))
    with pytest.raises(KeyError):
        a.read(["nope"])
