import asyncio
import importlib.util
import socket
import threading
import time
from pathlib import Path

import pytest
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.server import ServerAsyncStop, StartAsyncTcpServer


def block(values, cls=ModbusSequentialDataBlock):
    # Starts at 1: pymodbus servers add 1 to the requested address.
    return values if isinstance(values, ModbusSequentialDataBlock) else cls(1, list(values))


@pytest.fixture
def modbus_server():
    """Start an in-process Modbus TCP server on a free localhost port: start(ir=, hr=, co=) -> (port, stop)."""
    running = []

    def start(ir=(0,) * 200, hr=(0,) * 200, co=(False,) * 16):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        # di must be passed: pymodbus 3.9.2 ignores co/ir/hr when di is None.
        ctx = ModbusServerContext(
            slaves=ModbusSlaveContext(di=block([False] * 16), ir=block(ir), hr=block(hr), co=block(co)),
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
            if t.is_alive():
                asyncio.run_coroutine_threadsafe(ServerAsyncStop(), loop).result(5)
                t.join(5)

        running.append(stop)
        return port, stop

    yield start
    for stop in running:
        stop()


P2_USERS = {"zerostate": "zs-test-only", "operator": "op-test-only"}  # throwaway, in-process test server only


@pytest.fixture(scope="module")
def p2_server(tmp_path_factory):
    """P2's OPC UA server in-process on a free localhost port at x30: (url, plant, write log path).
    `plant` is the server's Plant (model + control). Module scope: a server takes seconds to build."""
    tmp_path = tmp_path_factory.mktemp("p2")
    spec = importlib.util.spec_from_file_location("p2_server", Path(__file__).parents[1] / "plants" / "p2_gasline" / "server.py")
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    running = []

    def start(scale: float = 30.0):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        url = f"opc.tcp://127.0.0.1:{port}/"
        loop = asyncio.new_event_loop()
        ready, box = threading.Event(), {}

        async def main():
            box["stop"] = asyncio.Event()
            await srv.serve(url, P2_USERS, tmp_path / "p2_writes.jsonl", scale, seed=0, ready=ready, stop=box["stop"], box=box)

        t = threading.Thread(target=lambda: loop.run_until_complete(main()), daemon=True)
        t.start()
        assert ready.wait(30), "P2 server did not start"

        def stop():
            if t.is_alive():
                loop.call_soon_threadsafe(box["stop"].set)
                t.join(10)

        running.append(stop)
        return url, box["plant"], tmp_path / "p2_writes.jsonl"

    yield start()
    for stop in running:
        stop()
